# 2026-10-28 驗證結果

23 項模擬測試通過：13 項新電腦端測試，10 項保留的 Cloud Run 後端測試。

電腦端：
- Firestore 值編解碼、空更新防護，避免不帶遮罩的更新破壞既有資料。
- 不覆寫原 dashboard、提醒或其他根欄位。
- 同時兩台電腦的執行權、全域時段領取與中斷保護。
- 手動核對後解除阻擋，但不重送原時段。
- 正常送出只執行一次、結果不明時暫停、限流冷卻跨時段保留。
- 雲端領取失敗時不送 TG；結果回報失敗後保留待確認狀態。
- 刪除帳號、無本機登入、無效排程都不執行。
- Firebase refresh token 輪替保存與管理員 UID 驗證。

另外：Python compileall、index.html 內嵌 JavaScript、desktop.js 的 node --check、HTML ID 唯一性。

未完成：Windows DPAPI / ACL / 開機自動啟動實機驗證；真實 Firebase 規則 / REST updateTime 衝突整合；TG 真實收碼與發訊；50 帳號負載；瀏覽器視覺測試。模擬測試不代表正式環境已可連線。

登入診斷更新：17 項電腦端測試通過，新增登入錯誤代碼與 API 限制原因辨識，確認不輸出回應內的密碼或 token。未進行真實 Firebase 帳密測試。
