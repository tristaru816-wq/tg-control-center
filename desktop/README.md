# TG Control Center 3.0 — Windows 執行、手機管理

沿用原 GitHub Pages 網站與 Firebase Authentication / Firestore。主模式改為 Windows 電腦主動讀取 Firebase 設定，執行 Telegram 工作並回報結果。**不需要 Cloud Run、Cloud Scheduler、公開電腦連接埠或同一個 Wi-Fi。**

網站：https://tristaru816-wq.github.io/tg-control-center/

## 第一次使用

1. 在 Windows 安裝 Python 3.11 或以上版本，安裝時包含 Python Launcher。
2. 下載 ZIP 並完整解壓到固定位置。從整個 GitHub 儲存庫下載者，進入 `desktop` 資料夾；獨立執行器 ZIP 則直接進入解壓後的資料夾。
3. 雙擊 `start.cmd`。第一次會安裝 Telethon、requests 與時區資料，需要網路。
4. 輸入原網站的 **Firebase 管理員信箱與密碼**（不是 Google 帳號密碼）。密碼輸入時不會顯示字元，輸入後按 Enter。
5. 若尚無帳號資料，先用手機登入原網站，在「帳號」頁新增名稱，等候 Firebase 同步。
6. 電腦選單選 `1`，選擇對應名稱，填自己的 TG 電話、API ID / API Hash，輸入 Telegram 驗證碼；需要時再填兩步驗證密碼。
7. 可重複選 `1` 登入其他帳號。完成後選 `2` 啟動同步與排程，保持電腦視窗開著。
8. 手機開原網站的「電腦執行」，確認電腦顯示已連線、TG 帳號可用。儲存執行排程後再按啟用。

日後雙擊 `start.cmd`，會以已保存的登入啟動執行。要新增帳號、更換管理員登入或登出 TG，先 Ctrl+C 停止執行器，再雙擊 `setup.cmd`。

自己的 Telegram API ID / Hash 可至 https://my.telegram.org 申請。不要把驗證碼、API Hash、密碼、Session 或 data 資料夾傳給其他人，也不必傳給 ChatGPT。

## 手機操作

- 原「帳號」頁管理名稱（最多 50 個）；「排程／考勤」頁繼續保留為原本草稿及提醒。
- **只有「電腦執行」頁啟用的排程才會實際執行**，既有草稿不會自動轉為群組發送。
- 每個帳號一組每日排程，可選 3、5、10、15 分鐘。台北時區，支援 22:00–02:00 跨午夜。
- 先以自己的測試帳號做「只檢查連線」，確定有新紀錄後，再使用自己的測試群組驗證文字打卡。
- 發送目標用可解析的公開 @username、機器人名稱或已加入群組 ID；群組權限與機器人指令需自行確認。
- 儲存排程會暫停，啟用前會再次確認。目前時段可能在下次輪詢立即執行；不補發先前錯過的時段。
- 連線檢查不保證 Telegram 顯示在線。訊息送出僅記錄 Telegram 接受，不代表機器人確認或真人出勤。
- 若「結果待確認」，先人工查看群組，再按「已核對結果，解除暫停」，最後自行啟用。原時段不會重送。
- 暫停指令需等電腦下次讀取，已開始或已送出的操作無法撤回。電腦忙於前一個帳號或網路延遲時，讀取與執行也會延後。

## 持續運行

Windows 須保持開機、連網且不進入睡眠；手機可關閉網站，也可使用行動網路。關閉程式、睡眠或斷網後不會執行；雲端指令不會在沒有執行器時自己發送。

每 15 秒輪詢設定、約每 30 秒回報心跳。超過 120 秒未回報，網頁顯示未連線／過期；網頁顯示的是最後已知狀態，不能保證裝置即時在線。

如需登入 Windows 後自動啟動，先完成首次登入，右鍵以 PowerShell 執行 `enable_startup.ps1`。若系統阻擋腳本，可將 `start.cmd` 的捷徑手動放進 Win+R → `shell:startup`。取消執行 `disable_startup.ps1` 或刪除捷徑。這不是登入 Windows 前執行的系統服務。

## 資料與保護

- 繼續使用原 Firebase 管理員與 `adminData/<原UID>`；原 dashboard 不覆寫。
- 電腦用 Firebase 使用者 token 與現有管理員規則，不需要下載服務帳號金鑰。
- 電腦只合併更新 `desktopLease`、`desktopStatus`，網頁只合併寫入 `desktopConfig`；用 Firestore updateTime 前置條件協調執行權與時段領取。
- 同一時間只允許一台電腦取得執行權；另一台等待租約到期。帳號時段在發送前先寫入雲端，結果不明時阻擋新發送；不能保證端到端恰好一次。
- Firebase refresh token 與本機 API 設定使用 Windows DPAPI 保存，只能由對應 Windows 使用者解密。管理員密碼、TG 驗證碼與兩步驗證密碼不持久保存。
- Telethon session 是本機 SQLite 檔，未另外加密；data 資料夾限制目前 Windows 使用者存取。擁有本機權限或拿到 session 的人仍可能存取 TG，請保護電腦，不要備份到公開或共用位置。
- `data/` 同時包含本機執行紀錄與已處理時段，請勿複製到其他正在運作的執行器；移動或更換 Windows 使用者需要重新登入。
- TG session 外洩時，從 Telegram 官方應用程式「裝置」撤銷相關登入。Firebase 管理登入可在電腦 `setup.cmd` 選單重新設定。
- 原 Cloud Run 選項保留在 backend，但本模式不會呼叫或建立雲端執行資源。如你曾自行啟動 Cloud Scheduler，切換前需停用其工作以避免兩種模式同時操作。

Firebase 仍有讀寫用量與原專案配額限制。本模式減少額外部署，但不代表所有 Firebase 用量永久免費。

## 驗證與限制

23 項模擬測試通過（13 項電腦端 + 10 項先前後端）：資料不覆寫、空更新防護、全域執行權、時段去重、發送不明時暫停、手動核對解除、限流、token 更新、跨日等。完成 Python 編譯與 JavaScript 語法檢查。

尚未進行 Windows DPAPI／自動啟動實機測試、真實 Firebase 規則與 updateTime 整合、TG 真實收碼／群組發訊、50 帳號負載與瀏覽器視覺測試。這是待你電腦完成首次驗收的原始碼版本，尚非已驗證 EXE。

未提供截圖打卡、機器人按鈕點擊及機器人回覆判讀。

## 開發測試

```bash
python -m pip install -r backend/requirements.txt -r desktop/requirements.txt pytest httpx
python -m pytest -q
```

技術參考：
- https://firebase.google.com/docs/reference/rest/auth
- https://firebase.google.com/docs/firestore/reference/rest/v1/projects.databases.documents
- https://docs.telethon.dev/en/stable/basic/signing-in.html
