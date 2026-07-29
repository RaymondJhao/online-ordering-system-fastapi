# Backend — 線上點餐自取系統 API

給後端開發者看的技術文件。專案整體介紹（含前端、架構圖、商業脈絡）請見
[根目錄 README](../README.md)；關鍵決策的取捨請見 [ADR](../docs/adr/)。
這份文件聚焦在：怎麼跑起來、目錄怎麼分工、測試怎麼寫、遇到問題怎麼查。

---

## 技術棧

| 分類 | 技術 |
|---|---|
| 框架 | FastAPI（ASGI，全 async） |
| ORM | SQLAlchemy 2.0 async + asyncpg |
| 資料庫 | PostgreSQL 16（`docker-compose.yml` 內建） |
| 遷移 | Alembic（async env.py，支援 offline 模式） |
| 認證 | PyJWT + bcrypt 自行實作，refresh 輪替 + 重用偵測 |
| 快取 | Redis：token 撤銷名單、限流計數、排程分散式鎖 |
| 限流 | 自行實作的 Redis 滑動視窗（Lua 腳本保證原子性） |
| 背景任務 | APScheduler（AsyncIOScheduler，由 lifespan 管理） |
| 金流 | 綠界科技 ECPay（測試環境） |
| API 文件 | FastAPI 自動產生 OpenAPI 3.1，路徑 `/docs` |
| 測試 | pytest + pytest-asyncio + httpx，跑在真實 Postgres 與 Redis 上 |
| 品質 | ruff（lint + format）、coverage |

---

## 目錄結構

```
backend/
├── alembic/                    # 資料庫遷移
│   ├── env.py                  # async 版設定，連線字串取自 Settings 而非寫死在 ini
│   └── versions/
├── app/
│   ├── main.py                 # FastAPI 實例、lifespan、/health
│   ├── core/                   # 與商業邏輯無關的基礎設施
│   │   ├── config.py           # pydantic-settings，啟動即驗證，金鑰為必填
│   │   ├── database.py         # async engine / sessionmaker / get_db 依賴
│   │   ├── redis.py            # Redis 連線池
│   │   ├── security.py         # 密碼雜湊、JWT 簽發與驗證
│   │   ├── rate_limit.py       # Redis 滑動視窗限流
│   │   └── scheduler.py        # AsyncIOScheduler + 分散式鎖
│   ├── models/                 # SQLAlchemy 2.0 Mapped[] 風格
│   ├── schemas/                # Pydantic v2：輸入驗證 + 回應序列化 + OpenAPI 來源
│   ├── services/               # 商業邏輯，可不透過 HTTP 直接測試
│   │   ├── auth_service.py     # 註冊、登入、token 輪替
│   │   ├── token_store.py      # Redis 上的 token 狀態
│   │   ├── order_service.py    # 建單、狀態機、冪等性
│   │   ├── stock_service.py    # 原子扣庫存
│   │   ├── coupon_service.py
│   │   ├── payment_service.py
│   │   ├── menu_service.py
│   │   └── maintenance_service.py  # 排程的實際工作
│   ├── api/
│   │   ├── deps.py             # get_current_user / require_role 等共用依賴
│   │   └── v1/                 # 路由：只做 HTTP 與例外轉換
│   └── utils/ecpay.py          # 綠界簽章演算法
├── scripts/seed.py             # 開發用測試資料（get-or-create，可重複執行）
├── tests/
├── Dockerfile                  # 多階段建置，非 root 執行
├── docker-compose.yml          # 本機 PostgreSQL + Redis
└── pyproject.toml              # 相依、ruff、pytest、coverage 設定集中於此
```

**分層原則**：依賴方向是 `api → services → models`，反向不允許。
路由函式只做三件事——呼叫 service、把領域例外轉成 HTTP 狀態碼、回傳序列化結果。
service 不知道 HTTP 的存在，因此可以直接寫單元測試（併發測試就是這樣寫的）。

---

## 快速開始

```bash
docker compose up -d                  # PostgreSQL + Redis

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 產生金鑰填入 .env

alembic upgrade head
python -m scripts.seed

uvicorn app.main:app --reload
```

---

## 設定

所有設定集中在 `app/core/config.py`，由 pydantic-settings 在啟動時驗證。
完整清單見 `.env.example`，幾個需要注意的：

| 變數 | 說明 |
|---|---|
| `SECRET_KEY` / `JWT_SECRET_KEY` | **必填**，無預設值。拒絕 `change-me` 這類佔位字串與長度不足 32 字元的值 |
| `DATABASE_URL` | 若填 `postgresql://` 會自動補成 `postgresql+asyncpg://`，方便直接使用雲端平台注入的值 |
| `BCRYPT_ROUNDS` | 預設 12。測試環境可設 4 讓整套測試從 50 秒降到 6 秒；正式環境低於 12 會啟動失敗 |
| `RATE_LIMIT_ENABLED` | 測試時設 `false`，否則重複呼叫下單 API 的測試會互相干擾 |
| `SCHEDULER_ENABLED` | 測試時設 `false` |
| `CORS_ORIGINS` | JSON 陣列與逗號分隔兩種寫法都支援 |

---

## 資料庫遷移

```bash
alembic upgrade head                              # 套用到最新
alembic revision --autogenerate -m "描述"          # 依 models 變更產生
alembic downgrade -1                              # 回滾一版
alembic check                                     # 檢查 models 與 migration 是否同步
alembic upgrade head --sql                        # 只輸出 SQL 不執行
```

CI 會跑 `alembic check`，擋下「改了 model 卻忘記產生 migration」——
這種問題測試會全綠（測試庫是用 migration 建的，只是少了新欄位），直到部署才炸開。

**Postgres 原生 ENUM 的注意事項**：autogenerate 產生的 `downgrade()` 只會 drop table，
不會 drop type，導致 `downgrade` 之後再 `upgrade` 會失敗（`type already exists`）。
首版 migration 已手動補上 `DROP TYPE`，日後新增 enum 時要記得比照處理。

---

## 測試

```bash
pytest                                # 全部
pytest tests/test_order_concurrency.py -v
pytest --cov --cov-report=term-missing
pytest -k "限流"                       # 測試名稱為中文，可直接用關鍵字篩選
```

### 測試策略

**跑在真實的 PostgreSQL 與 Redis 上，不用 SQLite 或 fakeredis。**
理由見 [ADR 0004](../docs/adr/0004-unify-on-postgres.md)：本專案最需要驗證的
併發正確性、原生 SQL 行為、Redis 的 `GETDEL` 原子性，在模擬品上驗證等於沒驗證。

**結構由 Alembic 建立**（`downgrade base` + `upgrade head`），
每次測試都順帶驗證 migration 可正確升級與回滾。

**兩種隔離方式**：

- 一般測試用 `db` fixture：綁在外層交易上，測試結束整筆 rollback，彼此完全隔離
- 併發測試用獨立 engine 與各自 commit 的 session，並在前後 TRUNCATE。
  **不能用共用 session** ——那樣所有操作在同一筆交易裡，天然沒有競爭

**測試函式名稱使用中文**，pytest 輸出可以直接當規格說明閱讀：

```
test_二十個並行請求搶五份庫存只會成功五筆
test_重用舊_refresh_token_會撤銷整條_family
test_取消時會把庫存還回去
```

---

## 常見問題

**`MissingGreenlet` 錯誤**
在 async 下存取未 eager load 的關聯就會發生。查詢時加上
`selectinload(Order.order_items).selectinload(OrderItem.menu_item)`。
`app/services/order_service.py` 的 `_eager_loaded()` 已封裝好訂單需要的兩層關聯。

**`The asyncio extension requires an async driver`**
`DATABASE_URL` 用了同步 driver。config 會自動處理 `postgresql://`，
但若填了 `postgresql+psycopg2://` 則需自行改為 `+asyncpg`。

**覆蓋率報告顯示函式主體大半沒被執行到，但測試明明通過**
SQLAlchemy 的 async 以 greenlet 實作，coverage 預設追蹤器在切換後會跟丟 frame。
`pyproject.toml` 已設定 `concurrency = ["thread", "greenlet"]`，
若自行執行 coverage 記得帶上這個設定。

**測試出現 `RuntimeError: Event loop is closed`**
連線池被 `lru_cache` 快取並綁在建立它的事件迴圈上，而每個測試各有一個迴圈。
`conftest.py` 的 `_isolate_cached_connections` fixture 會在測試間清除快取。

**排程沒有執行**
確認 `SCHEDULER_ENABLED=true`。多 worker 環境下每輪只有一個 worker 會實際執行
（Redis 分散式鎖），其餘會在 log 留下 `已由其他 worker 執行，本次略過`。
