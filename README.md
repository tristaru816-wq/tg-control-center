# TG Control Center

接續原有 Firebase Authentication + Firestore + GitHub Pages 專案。

## 現況

- 原本的管理員登入、帳號／排程／考勤提醒與雲端資料格式保留。
- 新增「連接 TG」頁：可呼叫後端取得 TG 驗證碼、兩步驗證登入、登出、檢查連線、設定並啟用每日排程。
- `backend/` 提供 Cloud Run 執行 API；Cloud Scheduler 每分鐘觸發，後端依每帳號 3／5／10／15 分鐘與台北時段判斷是否執行。
- **只更新 GitHub Pages 不會啟動後端。必須完成以下 Google Cloud 部署，才可真實連接 TG。**
- 尚未實作截圖打卡、機器人按鈕與回覆判讀；訊息被 Telegram 接受不表示機器人確認成功或真人在場。

## 完成一次雲端部署

需要使用有權管理 Firebase `tg-control-center` 專案的 Google 帳號登入 Google Cloud Shell。部署需啟用 Google Cloud 計費，Cloud Run、Firestore、Secret Manager、Cloud Build、Scheduler 可能產生用量費用。本儲存庫更新不會自動建立這些資源。

在 https://shell.cloud.google.com 開啟 Cloud Shell，執行：

```bash
git clone https://github.com/tristaru816-wq/tg-control-center.git
cd tg-control-center
bash backend/deploy.sh
```

如果已經下載過此儲存庫，請在原資料夾 `git pull` 後執行部署腳本。不要把 Telegram API Hash、驗證碼、密碼、Session 或服務帳號金鑰提交到 GitHub。

腳本會建立 runtime / scheduler 服務帳號、Secret Manager 加密金鑰、Cloud Run API 與每分鐘排程；最後只合併寫入原 `adminData/<管理員UID>` 的 `executionEndpoint` 欄位，保留 `dashboard` 與其他資料。金鑰若已存在會沿用，不會重建。

部署成功後重新登入原 GitHub Pages 網站，進入「連接 TG」，服務網址會自動載入。既有草稿與提醒不會自動轉為真實發送任務。

### 第一次驗收

1. 在「帳號」頁新增自己的測試帳號資料，確認 Firebase 已同步。
2. 在「連接 TG」頁選帳號，填國碼電話與你從 https://my.telegram.org 取得的 API ID / Hash，請求驗證碼。
3. 直接在網站輸入 TG 驗證碼；若回應需要兩步驗證，再輸入密碼。不要把這些資料傳到對話中。
4. 按「檢查連線」。確認成功後，設定目前時段、3 分鐘、只檢查連線並啟用。
5. 關閉網頁，幾分鐘後重開並按更新狀態，確認有新的台北時間結果。
6. 再使用自己的測試群組設定文字發送，啟用前會再次確認目標。確認實際群組只收到一則，再增加帳號數。

## 安全與執行規則

- 後端以 Firebase Admin SDK 驗證 ID token 及撤銷狀態，並限制原有管理員 UID；不使用共用管理密碼。
- Cloud Run 在入口允許公開 HTTP，但每個管理 API 都要求 Firebase 管理員 token。`/health` 無敏感資料；`/tick` 只接受指定 Scheduler 服務帳號的 Google OIDC token 與指定 audience。
- TG API Hash、StringSession、電話、排程內容先用 Fernet 加密再存入 Firestore；加密金鑰只在 Secret Manager。驗證碼與兩步驗證密碼不持久保存。
- Firestore 的 `_tgAccounts`、`_tgLocks`、`_tgRuns` 應拒絕所有前端 SDK 存取。附帶規則檔提供 TG 專案專用設定；部署腳本不會自行覆蓋你已發布的 Firestore 規則。
- 帳號 lease 使用 Firestore transaction，工作有逾時；每帳號每時段以唯一文件記錄，發送不明確時暫停，避免盲目補發。Telegram 網路發送無法保證端到端恰好一次。
- 網路中斷／程序中止後，請先人工核對群組，再按連線檢查清除待確認標記，最後自行啟用；不補發歷史時段。
- 開始時間包含、結束時間不包含，支援跨午夜。啟用時在目前區段內可能在下一次 Scheduler 呼叫立即執行；最多約一分鐘排程解析度，受雲端延遲影響。
- FloodWait 會保存冷卻時間，冷卻結束前不再執行；本時段不補發。
- 從原帳號頁刪除資料後，後端會在下一次排程呼叫暫停對應工作；已開始或已發送的操作無法撤回。要立即停用並撤銷 TG 授權請先按「暫停」與「登出 TG」。
- 執行帳號狀態與草稿分開保存，後台原「啟用設定」不等於 TG 已登入或排程已啟用。

## 權限與部署問題

必須先建立 Firestore（沿用既有的 default 資料庫）與 Firebase Email/Password 管理員。若部署提示計費未啟用或沒有權限，需由專案擁有者處理。若 Cloud Build 提示預設建置服務帳號缺權限，按錯誤中列出的建置帳號授予官方所需的 `roles/run.builder`，不要把 runtime 帳號設為專案擁有者。

若已更換網域，修改 `backend/deploy.sh` 的 `ALLOWED_ORIGINS`。Firebase 登入的授權網域也需包含該網域。這次預設沿用原 GitHub Pages。

若無法連接，先查看 Cloud Run 日誌、Cloud Scheduler 最近執行狀態與 Secret Manager 權限。勿在日誌中加入 token、驗證碼或 session。Scheduler 若沒有發出 OIDC token，確認專案的 Cloud Scheduler service agent 有其官方要求的服務代理角色。

請保留 Secret Manager `tg-session-key`；刪除或更換金鑰會讓既有 session 無法解密，屆時需先從 Telegram 官方應用程式「裝置」撤銷相關 session，再重新設定。

## 驗證與限制

本次通過 Python 後端模擬測試、Python 編譯、JavaScript 語法與部署腳本語法檢查。尚未在真實 Google Cloud 部署、驗證 Firestore transaction 整合、收取 TG 驗證碼、發送真實訊息或測試 50 帳號負載。瀏覽器視覺測試受當前環境限制，未完成。

```bash
python -m pip install -r backend/requirements.txt pytest httpx
python -m pytest -q
```

官方參考：
- https://firebase.google.com/docs/auth/admin/verify-id-tokens
- https://docs.cloud.google.com/run/docs/triggering/using-scheduler
- https://docs.cloud.google.com/scheduler/docs/http-target-auth
- https://docs.telethon.dev/en/stable/basic/signing-in.html
