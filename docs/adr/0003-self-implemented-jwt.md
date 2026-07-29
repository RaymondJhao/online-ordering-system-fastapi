# 0003. 自行實作 JWT 認證而非使用套件

**狀態**：已採用

## 背景

Flask 版用 `Flask-JWT-Extended`，它把簽發、驗證、blocklist、裝飾器全包好了。
FastAPI 沒有對等的東西——`fastapi.security.OAuth2PasswordBearer` 常被誤以為是
認證器，實際上它只做三件事：

1. 從 `Authorization` 標頭取出 Bearer token 字串
2. 取不到就回 401
3. 在 OpenAPI 註冊 security scheme，讓 Swagger UI 出現 Authorize 按鈕

它的回傳值是 `str`，它不知道那字串是 JWT、opaque token 還是亂打的。
「把字串變成已驗證的使用者」那段邏輯，必須自己寫。

這其實是 OAuth2 規範（RFC 6749）刻意的設計：規範沒有規定 access token 的格式，
token 可以是 JWT、可以是查表用的隨機字串。FastAPI 只實作協議層，
憑證層屬於應用層的安全決策。

## 考慮過的選項

**`fastapi-users`。** 功能完整，註冊、登入、密碼重設、OAuth 都有。
但本專案有兩張獨立的使用者表（`customers` / `merchants`），
要套進它的單一 user model 需要相當程度的改造。

**外部 IdP（Auth0 / Keycloak / Cognito）。**
實務上多數公司的正確選擇。但作品集要展示的能力會被隱藏——
能講的只剩「我接了 Auth0 的 SDK」。

**自行實作（PyJWT + Redis）。** 需要自己處理簽發、驗證、撤銷、輪替。

## 決定

自行實作。作品集的功能是讓面試官有東西可以問，
而 JWT 恰好是最容易被追問的題材：

- token 存哪？為什麼不放 localStorage？
- JWT 是無狀態的，那要怎麼登出？
- refresh token 被偷了怎麼辦？

這些問題只有實作過才答得出來。

## 實作重點

**Refresh token 輪替與重用偵測。**
每次換發都輪替，Redis 用**白名單**記錄目前有效的 refresh jti。
白名單而非黑名單是重用偵測的前提——一個簽章正確但不在名單上的 token，
代表它要嘛已被輪替掉、要嘛是偽造的，兩者都該視為異常，此時撤銷整條 token family。

取用時用 `GETDEL`（單一原子操作）而非「先 GET 再 DEL」，
否則兩個並行請求可能都拿到同一個 token 並各自輪替出新 token。

**撤銷名單改存 Redis 而非資料表。**
舊版的 `token_blocklist` 資料表沒有任何清理機制——token 早就過期失效了，
紀錄仍留在表裡永久累積，而且每次驗證都要查這張只增不減的表。
Redis 的 TTL 讓紀錄在 token 自然到期時一併消失。

> **更正（部署後補充）**：這份 ADR 原本寫「Redis 資料遺失的風險由 AOF 持久化
> 涵蓋」，那句話在本機的 docker-compose 成立，但**在正式環境不成立**——
> Render 免費方案的 Key Value 服務沒有持久化，重啟即資料全失。
>
> 實際的後果是：Redis 一被清空，所有 refresh token 都不在白名單上，
> 下次換發會被判定為重用而撤銷整條 family，**全站使用者同時被強制登出**。
> 方向上是 fail-safe（寧可誤殺不可放行），但這是既有設計的真實限制，
> 不該被一句「有 AOF」帶過。詳見 [ADR 0007](0007-free-tier-tradeoffs.md)。

**登出同時撤銷 access token 與整條 family。**
只撤銷 access token 是不夠的：攻擊者若同時持有 refresh token，
下一秒就能換出新的 access token，登出等於沒有效果。

## 代價

- **安全責任在自己身上。** `alg=none`、algorithm confusion、token 型別混用，
  每一項都要自己擋。因此寫了 11 個安全性測試，並用突變測試確認它們有效
  （移除 family 撤銷會讓 2 個測試失敗，移除 typ 檢查會讓 1 個失敗）。
- **沒有密碼重設、Email 驗證、社群登入。** 這些 `fastapi-users` 開箱即有。
- **維護成本長期高於套件。** 規模成長後應該重新評估。

## 什麼情況下這個決定會是錯的

如果這是真的要上線並長期維護的商業產品，接外部 IdP 幾乎一定更划算——
安全性由專業團隊維護，還附帶 SSO、MFA、稽核日誌。
這裡選擇自建，是因為專案目的是展示與學習，不是最小化維護成本。
