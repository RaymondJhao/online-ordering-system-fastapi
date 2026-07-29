# 0004. 開發／測試／正式統一使用 PostgreSQL

**狀態**：已採用

## 背景

Flask 版同時存在三套資料庫：

| 環境 | 資料庫 |
|---|---|
| 測試（conftest） | SQLite in-memory |
| 本機開發（docker-compose） | MySQL 8 |
| 正式（Render） | PostgreSQL |

`requirements.txt` 裡 `psycopg2-binary` 與 `PyMySQL` 並存。

測試用 SQLite 的理由很合理——快、隔離乾淨、不需要外部服務。
問題是這讓測試綠燈不再保證正式環境正確，而且**受影響最大的正是本專案最關鍵的邏輯**：

- 原子扣庫存用的是原生 SQL，各家資料庫的行為與鎖機制不同
- `Enum` 型別在 SQLite 是 VARCHAR，在 Postgres 是原生型別
- `Numeric`/`Decimal` 精度處理不同
- 交易隔離級別與行鎖行為完全不同——而併發正確性正是這個專案的賣點

換句話說，最需要被驗證的那部分，恰好是測試最不可靠的部分。

## 考慮過的選項

**維持 SQLite 測試。** 速度最快，但如上所述無法驗證關鍵行為。

**統一 MySQL。** 保留本機既有資料。但 Render 免費方案只提供 Postgres，
且 `aiomysql` 的成熟度不如 `asyncpg`。

**統一 Postgres。** 需要重建本機開發資料（有 seed 腳本，成本低）。

## 決定

統一 Postgres 16，測試也跑在真實資料庫上。
CI 用 GitHub Actions 的 `services: postgres`，本機用 docker-compose。

同樣的原則也套用在 Redis：測試不用 fakeredis，用真實 Redis。
`GETDEL` 的原子性、TTL 行為與 `EXISTS` 的語意是 refresh 輪替正確性的基礎，
用模擬品驗證等於沒有驗證。

## 代價

- **測試需要外部服務。** 不能光靠 `pytest` 就跑起來，要先 `docker compose up`。
  README 有寫清楚，CI 也已設定好。
- **測試變慢。** 但實測整套 109 個測試約 6 秒——真正的瓶頸是 bcrypt 而非資料庫，
  因此另外加了 `BCRYPT_ROUNDS` 設定讓測試環境用較低的成本因子
  （正式環境低於 12 會直接啟動失敗，避免設定被誤帶上線）。

## 附帶收穫

改用 Postgres 之後，`DateTime` 欄位缺少 `timezone=True` 的問題立刻浮現：
Python 端存的是 aware datetime，欄位卻是無時區，讀回來變成 naive，
背景排程拿它跟 aware 的 cutoff 比較會直接拋 `TypeError`。
這個 bug 在 SQLite 上不會出現，因此在舊版一直沒被發現——
它本身就是「測試環境要貼近正式環境」最好的例證。
