from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import os
import hashlib
from threading import Timer, Lock
from datetime import datetime
import requests

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
SCHEDULE_API_URL = os.environ.get(
    "SCHEDULE_API_URL",
    "https://schedule-app-2zqe.onrender.com",
).rstrip("/")
LINE_BRIDGE_API_KEY = os.environ.get("LINE_BRIDGE_API_KEY", "").strip()

# 保險檢查
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("未偵測到 LINE 環境變數，請檢查 Render 後台設定")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_states = {}
user_locks = {}
daily_records = {}


def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = Lock()
    return user_locks[user_id]


def reply_text(reply_token, text):
    line_bot_api.reply_message(reply_token, TextSendMessage(text=text))


def get_group_id(event):
    """只接受 LINE 群組來源；一對一聊天沒有 group_id。"""
    return getattr(event.source, "group_id", None)


def get_upload_target(branch, area):
    """回傳各分店/區域應上傳的照片數量。"""
    if branch == "潮州店":
        return 27 if area == "外場" else 14
    return 12 if area == "外場" else 11


def get_upload_note(branch, area):
    """回傳任務特殊提醒；沒有特殊項目時保持空白。"""
    if branch == "潮州店" and area == "外場":
        return "\n\n📌 本次外場新增 1 張：可樂機濾嘴確認照。"
    return ""


def extract_bridge_reply(data):
    """相容後端常見回傳欄位，最後仍保留可讀錯誤訊息。"""
    if isinstance(data, str):
        return data.strip()

    if not isinstance(data, dict):
        return ""

    for key in ("reply_text", "reply", "message", "text", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("reply_text", "reply", "message", "text", "content"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def extract_bridge_error(response, data):
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list) and detail:
            return str(detail[0])

    body = (response.text or "").strip()
    if body:
        return body[:300]
    return f"HTTP {response.status_code}"


def handle_schedule_command(group_id, command):
    """把 LINE 群組指令轉送到排班系統的橋接 API。"""
    if not group_id:
        return "⚠️ 請在已加入 Yihop 機器人的 LINE 群組中使用此指令。"

    if not SCHEDULE_API_URL:
        return "⚠️ 尚未設定 SCHEDULE_API_URL，請通知管理員。"

    if not LINE_BRIDGE_API_KEY:
        return "⚠️ 尚未設定 LINE_BRIDGE_API_KEY，請通知管理員。"

    endpoint = f"{SCHEDULE_API_URL}/line-bridge/command"
    headers = {
        "Content-Type": "application/json",
        "X-Line-Bridge-Api-Key": LINE_BRIDGE_API_KEY,
        "X-Line-Bridge-Key": LINE_BRIDGE_API_KEY,
        "X-API-Key": LINE_BRIDGE_API_KEY,
        "Authorization": f"Bearer {LINE_BRIDGE_API_KEY}",
    }

    # 第一種是目前橋接 API 的標準格式；若後端版本仍使用 line_group_id，
    # 只有在 422 驗證失敗時才安全地改用相容格式重試。
    payloads = [
        {"group_id": group_id, "command": command},
        {"line_group_id": group_id, "command": command},
        {"line_group_id": group_id, "text": command},
    ]

    last_response = None
    last_data = None

    try:
        for payload in payloads:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=20,
            )
            last_response = response

            try:
                data = response.json()
            except ValueError:
                data = None
            last_data = data

            if response.status_code == 422:
                continue

            if response.ok:
                reply = extract_bridge_reply(data)
                if reply:
                    return reply
                return "⚠️ 排班系統已回應，但沒有可顯示的崗位內容。"

            error = extract_bridge_error(response, data)
            if response.status_code in (401, 403):
                return f"⚠️ 排班系統驗證失敗：{error}"
            if response.status_code == 404:
                return f"⚠️ 找不到此群組的分店綁定或崗位資料：{error}"
            return f"⚠️ 排班系統暫時無法查詢：{error}"

        if last_response is not None:
            error = extract_bridge_error(last_response, last_data)
            return f"⚠️ 排班系統指令格式不相容：{error}"
        return "⚠️ 排班系統沒有回應。"

    except requests.Timeout:
        return "⚠️ 排班系統啟動或查詢逾時，請稍後再試一次。"
    except requests.RequestException as exc:
        print(f"Schedule bridge request failed: {exc}")
        return "⚠️ 目前無法連線到排班系統，請稍後再試。"


def check_upload_status(user_id, reply_token):
    lock = get_user_lock(user_id)
    with lock:
        if user_id in user_states:
            state = user_states[user_id]
            if state.get("step") != "uploading":
                return
            current_count = state["count"]
            target_count = state["target"]
            if current_count < target_count:
                shortfall = target_count - current_count
                reply_msg = (
                    f"📊 【進度回報】\n{state['branch']}的 {state['name']} 您好，"
                    f"您的 {state['area']} 任務為 {target_count} 張。\n\n"
                    f"目前已成功傳送：{current_count} 張\n"
                    f"⚠️ 還缺少：{shortfall} 張！\n\n"
                    "請繼續傳送剩餘的照片補齊。"
                )
                try:
                    reply_text(reply_token, reply_msg)
                except Exception:
                    pass


@app.route("/", methods=["GET"])
def ping():
    return "Bot is awake and running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        abort(400)

    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


# ▼▼▼MAIN_CODE_START▼▼▼
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    group_id = get_group_id(event)

    # LINE 群組綁定與排班查詢指令。
    if "群組ID" in raw_text.upper().replace(" ", ""):
        if group_id:
            reply_text(event.reply_token, f"此 LINE 群組 ID：\n{group_id}")
        else:
            reply_text(event.reply_token, "⚠️ 這裡不是 LINE 群組，無法取得群組 ID。")
        return

    schedule_command = None
    if "當日崗位" in raw_text:
        schedule_command = "當日崗位"
    elif "明日崗位" in raw_text:
        schedule_command = "明日崗位"

    if schedule_command:
        result = handle_schedule_command(group_id, schedule_command)
        reply_text(event.reply_token, result)
        return

    lock = get_user_lock(user_id)
    with lock:
        if (
            user_id in user_states
            and user_states[user_id].get("step") == "confirming_duplicate_area"
        ):
            state = user_states[user_id]
            if raw_text == "內場":
                state["area"] = "內場"
            elif raw_text == "外場":
                state["area"] = "外場"
            else:
                # 狀態存在時也只接受精確回覆；其他群組聊天保持安靜。
                return
            state["target"] = get_upload_target(state["branch"], state["area"])
            state["step"] = "uploading"
            reply_msg = (
                "✅ 已強制設定完畢！\n"
                "💡 小提醒：下次傳送前請先和夥伴確認好區域，才不會重複做白工喔！\n\n"
                f"分店：{state['branch']}\n"
                f"姓名：{state['name']}\n"
                f"區域：{state['area']}\n\n"
                f"請直接在聊天室一次選取並傳送 {state['target']} 張照片。"
                f"{get_upload_note(state['branch'], state['area'])}"
            )
            reply_text(event.reply_token, reply_msg)
            return

        if user_id in user_states and user_states[user_id].get("step") == "waiting_for_branch":
            state = user_states[user_id]
            branch_choice = {
                "1": "潮州店",
                "１": "潮州店",
                "2": "內埔店",
                "２": "內埔店",
            }.get(raw_text, "")
            if not branch_choice:
                # 避免曾開啟設定但未完成時，之後一般聊天一直觸發 Bot。
                return
            today_str = datetime.now().strftime("%Y-%m-%d")
            already_done_by = (
                daily_records.get(today_str, {})
                .get(branch_choice, {})
                .get(state["area"])
            )
            if already_done_by:
                state["branch"] = branch_choice
                state["step"] = "confirming_duplicate_area"
                reply_msg = (
                    f"⚠️ 【防呆警告】\n今天 {branch_choice} 的「{state['area']}」"
                    f"已經由 {already_done_by} 完成上傳囉！\n\n"
                    f"您確定還要設定為{state['area']}嗎？請問您是要設定內場還是外場呢？\n"
                    "(請直接回覆「內場」或「外場」進行強制設定)"
                )
                reply_text(event.reply_token, reply_msg)
                return

            state["branch"] = branch_choice
            state["target"] = get_upload_target(state["branch"], state["area"])
            state["step"] = "uploading"
            reply_text(
                event.reply_token,
                "✅ 已設定完畢！\n"
                f"分店：{state['branch']}\n"
                f"姓名：{state['name']}\n"
                f"區域：{state['area']}\n\n"
                f"請直接在聊天室一次選取並傳送 {state['target']} 張照片。"
                f"{get_upload_note(state['branch'], state['area'])}\n\n"
                "💡 傳送完畢後，系統會自動為您清點數量。",
            )
            return

        parts = raw_text.split()
        if parts and parts[0] == "設定":
            if len(parts) == 3:
                name, area = parts[1], parts[2]
                if area not in ["外場", "內場"]:
                    reply_text(event.reply_token, "⚠️ 區域請填寫「外場」或「內場」")
                    return
                if (
                    user_id in user_states
                    and "timer" in user_states[user_id]
                    and user_states[user_id]["timer"]
                ):
                    user_states[user_id]["timer"].cancel()

                user_states[user_id] = {
                    "step": "waiting_for_branch",
                    "name": name,
                    "area": area,
                    "count": 0,
                    "target": 0,
                    "branch": "",
                    "timer": None,
                    "hashes": set(),
                }
                reply_text(
                    event.reply_token,
                    "請選擇您所在的分店：\n1. 潮州店\n2. 內埔店\n\n(請直接回覆數字 1 或 2)",
                )
            else:
                reply_text(event.reply_token, "⚠️ 格式錯誤。\n請輸入例如： 設定 王小明 外場")
            return

        # 只有完整的「結算」或「完成」指令才觸發，避免一般聊天中出現
        # 「完成任務」等字樣時誤回覆「沒有正在進行的上傳任務」。
        if raw_text in {"結算", "完成"}:
            if user_id not in user_states or user_states[user_id].get("step") != "uploading":
                return
            state = user_states[user_id]
            if state["count"] < state["target"]:
                reply_text(
                    event.reply_token,
                    f"📊 【進度回報】\n目前已成功傳送：{state['count']} 張\n"
                    f"⚠️ 還缺少：{state['target'] - state['count']} 張！",
                )
            else:
                reply_text(event.reply_token, "✅ 您已全數傳送完畢，無需再補傳！")


# ▲▲▲MAIN_CODE_END▲▲▲
# ▼▼▼MAIN_CODE_START▼▼▼
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    if user_id not in user_states:
        return

    lock = get_user_lock(user_id)
    with lock:
        if user_id not in user_states:
            return
        state = user_states[user_id]
        if state.get("step") != "uploading":
            return

        if state.get("timer"):
            state["timer"].cancel()
            state["timer"] = None

        try:
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b""
            for chunk in message_content.iter_content():
                image_bytes += chunk

            img_hash = hashlib.md5(image_bytes).hexdigest()

            if img_hash in state["hashes"]:
                reply_msg = (
                    "⚠️ 發現重複照片！\n這張照片剛剛已經傳過了，系統將不計入數量。\n"
                    f"(目前進度：{state['count']} / {state['target']})"
                )
                reply_text(event.reply_token, reply_msg)
                return

            state["hashes"].add(img_hash)
            state["count"] += 1

            if state["count"] == state["target"]:
                today_str = datetime.now().strftime("%Y-%m-%d")
                if today_str not in daily_records:
                    daily_records.clear()
                    daily_records[today_str] = {}
                if state["branch"] not in daily_records[today_str]:
                    daily_records[today_str][state["branch"]] = {}
                daily_records[today_str][state["branch"]][state["area"]] = state["name"]

                reply_msg = (
                    f"🎉 恭喜！{state['branch']} {state['name']} 的{state['area']}清潔照共 "
                    f"{state['target']} 張已全數確認完畢！"
                )
                reply_text(event.reply_token, reply_msg)
                del user_states[user_id]
            else:
                timer = Timer(5.0, check_upload_status, args=[user_id, event.reply_token])
                state["timer"] = timer
                timer.start()

        except Exception as exc:
            error_str = str(exc)
            # 針對 410 錯誤與一般超載錯誤進行 UX 優化攔截
            if "status_code=410" in error_str or "content is gone" in error_str:
                error_message = (
                    "⚠️ LINE 伺服器瞬間塞車，剛剛有一張照片傳輸失敗了。\n"
                    f"(目前進度：{state['count']} / {state['target']})\n"
                    "請幫我重新補傳一張！"
                )
            else:
                error_message = (
                    "❌ 系統瞬間載入量過大，漏接了一張照片。\n"
                    f"(目前進度：{state['count']} / {state['target']})\n"
                    "請幫我重新補傳一張！"
                )

            print(f"Error caught: {error_str}")
            try:
                reply_text(event.reply_token, error_message)
            except Exception:
                pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
# ▲▲▲MAIN_CODE_END▲▲▲
