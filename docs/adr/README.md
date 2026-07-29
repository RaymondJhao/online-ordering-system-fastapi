# 架構決策紀錄（ADR）

這裡記錄的是「為什麼這樣做」，而不是「怎麼做」——後者程式碼與註解已經說明了。

每一則都包含當時面對的問題、被認真考慮過的選項、最後的取捨，以及這個決定的代價。
會寫下代價，是因為沒有代價的決定通常代表沒有真的做過選擇。

| 編號 | 決策 | 狀態 |
|---|---|---|
| [0001](0001-migrate-flask-to-fastapi.md) | 從 Flask 遷移到 FastAPI | 已採用 |
| [0002](0002-async-sqlalchemy.md) | 資料層全面改為 async | 已採用 |
| [0003](0003-self-implemented-jwt.md) | 自行實作 JWT 認證而非使用套件 | 已採用 |
| [0004](0004-unify-on-postgres.md) | 開發／測試／正式統一使用 PostgreSQL | 已採用 |
| [0005](0005-atomic-stock-deduction.md) | 以資料庫層原子操作防止超賣 | 已採用 |
| [0006](0006-custom-rate-limiter.md) | 自行實作 Redis 限流而非使用套件 | 已採用 |
