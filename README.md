# Yihop LINE Bot｜門市清潔 SOP 與排班系統整合

> 以 LINE Webhook 接收門市清潔照片與文字操作，保留每日回報進度；程式亦包含與獨立排班 API 的橋接指令。

**[查看 GitHub 面試作品導覽](https://github.com/garyai8146-jpg/Yihop_LineBOT/blob/main/PORTFOLIO.md)**

## 用途與流程

```text
LINE 訊息／清潔照片
    → Flask Webhook、LINE 簽章驗證
    → 文字指令／多輪狀態
    ├─ 影像內容 MD5 去重與張數累計
    └─ 授權的排班 API 橋接請求
    → 回覆 LINE 使用者
```

## 工程重點

- **Webhook：** Flask + LINE Messaging API SDK 解析訊息事件並驗證來源。
- **照片：** 以 MD5 判斷位元內容相同的照片；無法偵測重新拍攝、修改壓縮過的相似照片。
- **多人操作：** 運用記憶體字典及部分 Lock 保護狀態；進程重啟、水平擴充與資料稽核仍需持久層。
- **排班橋接：** 透過 `SCHEDULE_API_URL` 與 `LINE_BRIDGE_API_KEY` 呼叫外部排班後端；實際權限應由後端驗證，不能單靠 LINE 文字辨識。

## 本機開發

```powershell
python -m pip install -r requirements.txt
python app.py
```

需要環境變數 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`，排班橋接另需 `SCHEDULE_API_URL` 和 `LINE_BRIDGE_API_KEY`。再於 LINE Developers 綁定有 HTTPS 的 Webhook。

## 安全與限制

此倉庫是流程整合原型，沒有可公開重現的完整營運端到端測試。不得提交 Channel Token、API 金鑰、使用者 ID、私人對話或門市照片。正式多店部署需要持久化紀錄、身分與群組授權、Webhook 重送的冪等性，以及競態測試。

## 面試展示

可從 LINE Webhook 的事件模型、共享狀態與鎖的限制、外部系統串接、資料重送與驗章等方面講解設計取捨。
