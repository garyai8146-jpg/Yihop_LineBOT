# LINE 清潔回報小幫手｜把群組裡的照片整理成進度

門市員工習慣直接在 LINE 群組回報清潔照片，但照片一多，就很難快速確認哪些區域完成了、哪些還欠幾張。

我把這個日常流程做成 LINE Bot：員工照原本的方式傳訊息、傳照片，系統負責處理指令、累計回報狀態和回覆結果；程式也包含與獨立排班系統 API 溝通的橋接功能。

**[查看完整面試作品集](https://github.com/garyai8146-jpg/Yihop_LineBOT/blob/main/PORTFOLIO.md)**

## 核心流程

```text
LINE 訊息或照片
    ↓
Flask Webhook：驗證 LINE 簽章
    ↓
辨識操作指令、處理目前的回報狀態
    ├─ 照片 MD5 比對、數量與進度統計
    └─ 有設定時呼叫排班系統 API
    ↓
回覆 LINE 訊息
```

## 實作時遇到的問題

**一張照片重傳怎麼辦？** 目前用 MD5 判斷內容相同的檔案，能減少完全相同圖片重複計數，但不能保證抓出「重新拍的舊照片」。

**多人一起操作怎麼辦？** 部分共享狀態使用 Lock 保護，降低同時修改的衝突；但目前狀態仍有放在記憶體裡的部分，伺服器重啟或擴成多個進程時，應改用持久化資料庫。

**怎麼跟其他系統溝通？** 透過後端設定的 API 位址與橋接憑證呼叫排班服務。真正的權限必須由伺服器驗證，不能只因為是 LINE 訊息就當成已授權。

## 本機執行

```powershell
python -m pip install -r requirements.txt
python app.py
```

需自行設定 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`。排班橋接另需 `SCHEDULE_API_URL` 與 `LINE_BRIDGE_API_KEY`。LINE Developers 的 Webhook 必須使用有效的 HTTPS 網址。

## 目前範圍

這是可檢視程式碼的流程整合原型；沒有公開真實員工資料、照片或 LINE Token。正式多店使用前，仍需補齊持久化、事件重送的冪等性、權限稽核與完整的整合測試。
