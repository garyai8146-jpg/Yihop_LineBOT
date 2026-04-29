from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import os
import hashlib
from threading import Timer, Lock
from datetime import datetime

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

# 保險檢查
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("未偵測到環境變數，請檢查 Render 後台設定")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_states = {}
user_locks = {}
daily_records = {} 

def get_user_lock(user_id):
    if user_id not in user_locks:
        user_locks[user_id] = Lock()
    return user_locks[user_id]

def check_upload_status(user_id, reply_token):
    lock = get_user_lock(user_id)
    with lock:
        if user_id in user_states:
            state = user_states[user_id]
            if state.get("step") != "uploading": return
            current_count = state['count']
            target_count = state['target']
            if current_count < target_count:
                shortfall = target_count - current_count
                reply_msg = f"📊 【進度回報】\n{state['branch']}的 {state['name']} 您好，您的 {state['area']} 任務為 {target_count} 張。\n\n目前已成功傳送：{current_count} 張\n⚠️ 還缺少：{shortfall} 張！\n\n請繼續傳送剩餘的照片補齊。"
                try:
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_msg))
                except:
                    pass

@app.route("/", methods=['GET'])
def ping():
    return "Bot is awake and running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'
# ▼▼▼MAIN_CODE_START▼▼▼
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    raw_text = event.message.text.strip()
    lock = get_user_lock(user_id)
    with lock:
        if user_id in user_states and user_states[user_id].get("step") == "confirming_duplicate_area":
            state = user_states[user_id]
            if "內場" in raw_text: state["area"] = "內場"
            elif "外場" in raw_text: state["area"] = "外場"
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請直接回覆「內場」或「外場」來確認您的區域。"))
                return
            state["target"] = (19 if state["area"] == "外場" else 28) if state["branch"] == "潮州店" else (12 if state["area"] == "外場" else 11)
            state["step"] = "uploading"
            reply_msg = f"✅ 已強制設定完畢！\n💡 小提醒：下次傳送前請先和夥伴確認好區域，才不會重複做白工喔！\n\n分店：{state['branch']}\n姓名：{state['name']}\n區域：{state['area']}\n\n請直接在聊天室一次選取並傳送 {state['target']} 張照片。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
            return

        if user_id in user_states and user_states[user_id].get("step") == "waiting_for_branch":
            state = user_states[user_id]
            branch_choice = "潮州店" if "1" in raw_text or "１" in raw_text else ("內埔店" if "2" in raw_text or "２" in raw_text else "")
            if not branch_choice:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入有效的數字：\n1. 潮州店\n2. 內埔店"))
                return
            today_str = datetime.now().strftime('%Y-%m-%d')
            already_done_by = daily_records.get(today_str, {}).get(branch_choice, {}).get(state["area"])
            if already_done_by:
                state["branch"] = branch_choice
                state["step"] = "confirming_duplicate_area"
                reply_msg = f"⚠️ 【防呆警告】\n今天 {branch_choice} 的「{state['area']}」已經由 **{already_done_by}** 完成上傳囉！\n\n您確定還要設定為{state['area']}嗎？請問您是要設定內場還是外場呢？\n(請直接回覆「內場」或「外場」進行強制設定)"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
                return
            else:
                state["branch"] = branch_choice
                state["target"] = (19 if state["area"] == "外場" else 28) if state["branch"] == "潮州店" else (12 if state["area"] == "外場" else 11)
                state["step"] = "uploading"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已設定完畢！\n分店：{state['branch']}\n姓名：{state['name']}\n區域：{state['area']}\n\n請直接在聊天室一次選取並傳送 {state['target']} 張照片。\n\n💡 傳送完畢後，系統會自動為您清點數量。"))
                return

        if "設定" in raw_text:
            clean_text = raw_text[raw_text.find("設定"):]
            parts = clean_text.split()
            if len(parts) >= 3:
                name, area = parts[1], parts[2]
                if area not in ["外場", "內場"]:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 區域請填寫「外場」或「內場」"))
                    return
                if user_id in user_states and 'timer' in user_states[user_id] and user_states[user_id]['timer']:
                    user_states[user_id]['timer'].cancel()
                
                user_states[user_id] = {"step": "waiting_for_branch", "name": name, "area": area, "count": 0, "target": 0, "branch": "", "timer": None, "hashes": set()}
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請選擇您所在的分店：\n1. 潮州店\n2. 內埔店\n\n(請直接回覆數字 1 或 2)"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 格式錯誤。\n請輸入例如： 設定 王小明 外場"))
            return

        if "結算" in raw_text or "完成" in raw_text:
            if user_id in user_states and user_states[user_id].get("step") == "uploading":
                state = user_states[user_id]
                if state['count'] < state['target']:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"📊 【進度回報】\n目前已成功傳送：{state['count']} 張\n⚠️ 還缺少：{state['target'] - state['count']} 張！"))
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ 您已全數傳送完畢，無需再補傳！"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 您目前沒有正在進行的上傳任務。"))
# ▲▲▲MAIN_CODE_END▲▲▲
# ▼▼▼MAIN_CODE_START▼▼▼
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    if user_id not in user_states: return

    lock = get_user_lock(user_id)
    with lock:
        if user_id not in user_states: return
        state = user_states[user_id]
        if state.get("step") != "uploading": return
        
        if state.get('timer'):
            state['timer'].cancel()
            state['timer'] = None
        
        try:
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b""
            for chunk in message_content.iter_content():
                image_bytes += chunk
                
            img_hash = hashlib.md5(image_bytes).hexdigest()
            
            if img_hash in state['hashes']:
                reply_msg = f"⚠️ 發現重複照片！\n這張照片剛剛已經傳過了，系統將不計入數量。\n(目前進度：{state['count']} / {state['target']})"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
                return
                
            state['hashes'].add(img_hash)
            state['count'] += 1

            if state['count'] == state['target']:
                today_str = datetime.now().strftime('%Y-%m-%d')
                if today_str not in daily_records:
                    daily_records.clear()
                    daily_records[today_str] = {}
                if state['branch'] not in daily_records[today_str]:
                    daily_records[today_str][state['branch']] = {}
                daily_records[today_str][state['branch']][state['area']] = state['name']

                reply_msg = f"🎉 恭喜！{state['branch']} {state['name']} 的{state['area']}清潔照共 {state['target']} 張已全數確認完畢！"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
                del user_states[user_id] 
            else:
                t = Timer(2.0, check_upload_status, args=[user_id, event.reply_token])
                state['timer'] = t
                t.start()

        except Exception as e:
            error_str = str(e)
            # 針對 410 錯誤與一般超載錯誤進行 UX 優化攔截
            if "status_code=410" in error_str or "content is gone" in error_str:
                error_message = f"⚠️ LINE 伺服器瞬間塞車，剛剛有一張照片傳輸失敗了。\n(目前進度：{state['count']} / {state['target']})\n請幫我重新補傳一張！"
            else:
                error_message = f"❌ 系統瞬間載入量過大，漏接了一張照片。\n(目前進度：{state['count']} / {state['target']})\n請幫我重新補傳一張！"
            
            print(f"Error caught: {error_str}")
            try:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_message))
            except:
                pass

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
# ▲▲▲MAIN_CODE_END▲▲▲
