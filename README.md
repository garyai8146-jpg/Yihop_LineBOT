# 餐廳清潔 SOP LINE Bot｜Closing Checklist Automation

> 透過員工熟悉的 LINE 對話介面，協助門市進行清潔照片回報、進度計數與缺漏提醒。

## 為什麼做

門市每日清潔查核需要反覆追問「哪個區域還沒交照片？」；只靠群組訊息容易漏掉回報。這個專案把清潔流程轉成 LINE Bot 的引導式對話，讓回報步驟與狀態更容易追蹤。

## 核心流程

```text
LINE 清潔回報
    → Webhook 驗章與事件解析
    → 文字指令／任務狀態處理
    → 取得照片位元內容
    → MD5 重複檔案檢查
    → 更新張數與待補項目
    → LINE 訊息回覆
```

## 工程設計

- **Webhook 整合：** Flask 搭配 LINE Messaging API SDK，處理門市人員的互動事件。
- **多輪任務狀態：** 透過記憶體中的任務狀態保存回報進度，降低操作步驟。
- **重複檔案偵測：** 計算影像內容雜湊，對完全相同位元內容的重複提交提出提醒。
- **併發保護：** 以 `threading.Lock` 控制共享狀態的部分修改，減少多筆回報同時進入時的衝突。
- **圖片處理取捨：** 不必把全部照片長期儲存在應用伺服器上，但仍需遵守 LINE 與營運端的資料保留規範。

## 技術棧

Python · Flask · LINE Messaging API · threading · hashlib · Render（部署選項）

## 執行與設定

```bash
python -m pip install -r requirements.txt
python app.py
```

使用前需於環境變數設定 LINE Channel Secret、Channel Access Token 等設定，並在 LINE Developers 登記 HTTPS Webhook。**絕對不要提交 Token、門市照片或真實員工個資。**

## 面試可以談什麼

LINE Webhook 事件模型、如何設計對話狀態機、圖片重複判定與記憶體／資料庫取捨、多人同時操作的競態問題，以及現場 SOP 數位化。

## 已知限制與下一步

MD5 比對只適合偵測位元內容相同的照片，不等於辨識是否使用舊照片、重新拍攝或修改後重傳。純記憶體狀態在服務重啟、水平擴充時也有持久性限制；若導入多店正式營運，應增加持久化、稽核及權限設計。
