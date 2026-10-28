# 2026-10-28 驗證

10 個模擬後端測試通過：
- Firebase token 缺失／管理員 UID／撤銷失效時拒絕存取。
- CORS 不允許未設定來源；API 回傳不包含電話、API Hash 或 Session。
- Firestore 帳號資料先加密後儲存，可解密還原。
- 時段與訊息驗證、儲存排程後暫停、跨午夜與結束邊界。
- TG 兩步驗證流程，驗證碼與密碼不寫入帳號紀錄。
- 相同時段只送一次、逾時後暫停、FloodWait 冷卻。
- 中斷工作不自動重播、刪除帳號資料後下次 tick 暫停。

另外完成：Python compileall、頁面兩段內嵌 JavaScript 與 telegram.js 的 node --check、HTML ID 唯一性、bash -n backend/deploy.sh。

未完成：Google Cloud 實際部署、真實 Firestore transaction 整合、TG 真實登入／發訊、50 帳號負載、瀏覽器視覺測試。測試不能證明正式環境已可使用。
