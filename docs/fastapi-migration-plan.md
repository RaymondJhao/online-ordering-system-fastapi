# Flask → FastAPI 遷移計畫

**專案**：online-ordering-system
**範圍**：`backend/`（約 1,200 行 Python，7 個 blueprint、3 個測試檔）
**日期**：2026-07-29

---

## 0. 已確認的四項決策

| 項目 | 決策 | 影響 |
|---|---|---|
| 遷移策略 | 一次性完整重寫 | 建立乾淨結構，不留混合痕跡 |
| 資料庫層 | 全面 async | async SQLAlchemy 2.0 + asyncpg；測試全改寫 |
| 認證層 | 升級 PyJWT + refresh 輪替 | 新增 refresh token、重用偵測、Redis blocklist |
| 本次產出 | 遷移計畫文件 | 確認後再動手 |

---

## 1. 現況盤點

**目前架構**

```
backend/app/
  __init__.py      create_app() factory，註冊 7 個 blueprint
  config.py        os.environ 讀取，含 dev fallback
  extensions.py    db / bcrypt / jwt / limiter 四個 Flask 擴充
  models.py        219 行，8 個 model，Flask-SQLAlchemy db.Model 風格
  tasks.py         APScheduler 每分鐘取消逾時未付款訂單
  routes/          auth 176 / order 505 / menu 134 / payment 89 / coupon 87 / inventory 35
  utils/ecpay.py   綠界 CheckMacValue 計算
tests/             conftest + auth / menu / orders
```

**做得好、值得原封保留的部分**

- `_deduct_stock()` 用單一 `UPDATE ... WHERE stock >= :qty` 做原子扣庫存，避免超賣。這段邏輯正確且有註解說明，直接搬。
- `Idempotency-Key` 防重複下單，含 `IntegrityError` 的併發競態處理。
- `TokenBlocklist` 讓 JWT 可撤銷。
- 綠界回調用 `CheckMacValue` 驗證來源。
- 測試刻意隔離到記憶體 SQLite，避免污染開發資料庫。

這幾點在轉職作品集裡是加分項，遷移過程中不要弄丟。

---

## 2. 元件對照表

| Flask 現況 | FastAPI 對應 | 難度 | 備註 |
|---|---|---|---|
| `create_app()` factory | `FastAPI()` + `lifespan` | 低 | `WERKZEUG_RUN_MAIN` 那段 hack 直接刪除 |
| Blueprint | `APIRouter(prefix=..., tags=...)` | 低 | 幾乎一對一 |
| `Config` + `os.environ` | `pydantic-settings.BaseSettings` | 低 | 順便移除不安全的 dev fallback |
| Flask-SQLAlchemy `db.Model` | SQLAlchemy 2.0 `DeclarativeBase` + `Mapped[]` | **高** | 全部 8 個 model 重寫 |
| `Model.query.filter_by()` | `await session.scalar(select(...))` | **高** | 散落在所有路由，量最大 |
| `db.session`（全域） | `AsyncSession` 依賴注入 `Depends(get_db)` | 中 | 需重新設計交易邊界 |
| Flask-Bcrypt | `bcrypt` 直接呼叫 + `anyio.to_thread` | 中 | 見 §5 阻塞陷阱 |
| Flask-JWT-Extended | `OAuth2PasswordBearer` + `PyJWT` | 中 | 邏輯自建，見 §4 |
| `@jwt_required()` | `Depends(get_current_user)` | 中 | 角色檢查改成 `require_role("merchant")` 依賴 |
| `token_in_blocklist_loader` | `get_current_user` 內查 Redis | 中 | DB → Redis，加 TTL 自動清理 |
| Flask-Limiter | `fastapi-limiter`（Redis 原生 async） | 中 | `slowapi` 是另一選項但維護較弱 |
| flasgger + 手寫 YAML docstring | FastAPI 自動 OpenAPI 3.1 | 低 | **淨刪除**，見下 |
| `request.get_json()` + 手動驗證 | Pydantic v2 request model | 中 | 大量 `if not x: return 400` 消失 |
| `jsonify(...)`, `return ..., 400` | `response_model` + `HTTPException` | 中 | |
| `request.form`（綠界回調） | `Request.form()` / `Form(...)` | 低 | 回應改 `PlainTextResponse("1\|OK")` |
| `BackgroundScheduler` | `AsyncIOScheduler` 於 lifespan 啟動 | 中 | 多 worker 問題見 §6 |
| `gunicorn run:app` | `gunicorn -k uvicorn.workers.UvicornWorker` | 低 | 改 `render.yaml` |
| pytest-flask `client` | `httpx.AsyncClient` + `ASGITransport` | **高** | conftest 全改寫 |

**flasgger 的淨收益值得單獨講**：`routes/auth.py` 的 `login` 有 **60 行 YAML docstring** 只為了產生文件，佔該函式一半以上篇幅。FastAPI 用 Pydantic model 取代後，同樣的文件品質約需 8 行，而且與實際驗證邏輯永遠同步——不會出現「文件寫 required 但程式沒擋」的漂移。這是最容易展示的遷移價值。

---

## 3. 目標結構

```
backend/
  pyproject.toml
  alembic.ini
  alembic/versions/
  app/
    main.py                 FastAPI 實例 + lifespan + router 掛載
    core/
      config.py             Settings(BaseSettings)
      database.py           async engine / async_sessionmaker / get_db
      security.py           JWT 簽發驗證、密碼雜湊
      redis.py              Redis 連線池（blocklist + limiter 共用）
      scheduler.py          AsyncIOScheduler
    models/                 base.py + customer / merchant / menu / order / coupon / token
    schemas/                auth / menu / order / coupon / common
    api/
      deps.py               get_db / get_current_user / require_role
      v1/                   auth / menu / order / coupon / inventory / payment
    services/               order_service / stock_service / coupon_service
    utils/ecpay.py          原封不動搬移
  tests/
```

**新增 `services/` 層的理由**：目前 `order.py` 有 505 行，路由函式同時處理 HTTP 解析、商業邏輯、資料存取。抽出 service 層後路由只剩 10~15 行，商業邏輯可獨立單元測試（不用起 HTTP client）。面試時「為什麼分層」是很好回答的題目，也讓 `order.py` 從專案最可怕的檔案變成最好講的檔案。

---

## 4. 認證層設計

**端點**

| 端點 | 用途 | Body |
|---|---|---|
| `POST /api/auth/register` | 註冊 | JSON |
| `POST /api/auth/login` | 前端登入（維持現有契約） | JSON `{role, email, password}` |
| `POST /api/auth/token` | OAuth2 標準端點，供 Swagger Authorize | form-encoded |
| `POST /api/auth/refresh` | 換發 access token（含輪替） | JSON `{refresh_token}` |
| `POST /api/auth/logout` | 撤銷整條 token family | Bearer |

保留 `/login`（JSON）是為了不動 React 前端；同時提供 `/token`（form）是因為 `OAuth2PasswordBearer` 的 `tokenUrl` 指向的端點必須吃 form-encoded，Swagger UI 的 Authorize 按鈕才能運作。兩者共用同一份 service 函式。這個取捨在 README 寫清楚，是個好的討論點。

**Token 設計**

- access token：15 分鐘，claims 含 `sub`（user id）、`role`、`jti`、`exp`、`iat`、`typ: "access"`
- refresh token：7 天，額外帶 `family_id`，`typ: "refresh"`
- 驗證時明確指定 `algorithms=["HS256"]`，並檢查 `typ` 欄位——避免拿 refresh token 當 access token 用

**Refresh 輪替與重用偵測**

每次 refresh 換發新的一組 token，舊的 refresh 立刻標記為已使用。若偵測到「已使用過的 refresh token 再次被送上來」，代表 token 已外洩，直接撤銷整個 `family_id` 底下所有 token，強制重新登入。

Redis 結構：

```
revoked:jti:{jti}          -> "1"   TTL = token 剩餘壽命
refresh:used:{jti}         -> family_id
revoked:family:{family_id} -> "1"   TTL = refresh 壽命
```

用 TTL 讓過期資料自動消失，不需要清理排程——這是相對現有 `TokenBlocklist` 資料表（會無限成長、沒有清理機制）的明確改進。

---

## 5. Async 特有陷阱

這些是改成 async 之後最容易踩、且錯誤訊息不直觀的地方，先寫下來避免除錯時間失控。

**5.1 Lazy loading 會直接炸掉（最高風險）**

async 下存取未載入的 relationship 會拋 `MissingGreenlet`，而不是自動發 SQL。現有 models 大量使用 `relationship()`，且 `MenuItem.orders` / `Order.menu_items` 用了 `association_proxy`——**association_proxy 在 async 下尤其麻煩**。

對策：

- 所有需要關聯資料的查詢明確加 `selectinload()` / `joinedload()`
- `Base` 繼承 `AsyncAttrs`，必要時用 `await obj.awaitable_attrs.orders`
- 序列化改由 Pydantic `from_attributes=True` 負責，`serialize_order()` 那類手寫函式退場
- **建議評估直接移除兩個 association_proxy**，改在 service 層明確查詢；它們目前的使用率需先確認

**5.2 bcrypt 是 CPU 阻塞操作**

`bcrypt` 雜湊需要約 100~300ms 的純 CPU 運算。在 `async def` 路由裡直接呼叫會**卡住整個 event loop**，讓所有並行請求一起變慢——這比 Flask 的同步模型更糟。

對策：`await anyio.to_thread.run_sync(bcrypt.checkpw, ...)`。這一點是很好的面試素材：能講清楚「為什麼 async 不是無腦比較快」通常會留下印象。

**5.3 測試資料庫的落差**

目前測試用 SQLite、docker-compose 用 MySQL、Render 用 Postgres——**三套不同資料庫**，requirements 裡 `psycopg2-binary` 和 `PyMySQL` 並存。這在 `text()` 原生 SQL、Enum 型別、`Decimal` 精度、交易隔離級別上都有行為差異，等於測試綠燈不保證正式環境正確。

建議藉這次遷移**統一為 Postgres**：

- 測試改用 `testcontainers-python` 起真實 Postgres，或 CI 用 GitHub Actions 的 `services: postgres`
- 若仍要保留 SQLite 快速路徑，需 `aiosqlite` + `StaticPool` + `check_same_thread=False`，否則每個連線都是各自獨立的空記憶體資料庫

推薦前者。這也讓 `_deduct_stock()` 的原子性在測試中真正被驗證。

**5.4 交易邊界要重新設計**

Flask-SQLAlchemy 的 `db.session` 是 request-scoped 全域物件；async 改成 `Depends(get_db)` 注入後，session 生命週期由依賴管理。`order.py` 裡跨多個 helper 函式共用 session 並在中途 `rollback()` 的寫法需要重整——建議 session commit/rollback 統一收斂到 service 層單一進入點。

**5.5 DateTime 遺失時區（既有缺陷）**

`models.py` 存的是 `datetime.now(timezone.utc)`（aware），但欄位定義是 `db.Column(db.DateTime)`（無 `timezone=True`）。資料庫會把時區資訊丟掉，讀回來變成 naive datetime。`tasks.py` 拿它跟 aware 的 `cutoff_time` 比較，在 Postgres 上會直接拋 `TypeError`。

遷移時一律改為 `mapped_column(DateTime(timezone=True))`。**這是既有的真 bug，順手修掉。**

---

## 6. 順帶處理的既有問題

| 問題 | 現況 | 處理 |
|---|---|---|
| 無資料庫遷移工具 | `db.create_all()` | 導入 Alembic，首版 migration 對齊現有 schema |
| 三套資料庫不一致 | SQLite / MySQL / Postgres | 統一 Postgres（見 5.3） |
| DateTime 無時區 | 見 5.5 | `DateTime(timezone=True)` |
| 密鑰有 dev fallback | `os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-key")` | pydantic-settings 設為必填，缺少即啟動失敗 |
| 排程多 worker 重複執行 | Render 上 gunicorn 多 worker 時每個 worker 都會跑排程 | Redis 分散式鎖，或獨立 worker process |
| blocklist 無限成長 | `TokenBlocklist` 資料表無清理 | Redis TTL 自動過期 |
| 測試覆蓋不均 | payment / coupon / inventory 無測試 | 遷移後補上 |
| 無 linter | CI 只跑 pytest | 加 `ruff check` + `ruff format --check` |

---

## 7. 分階段執行

每階段結束都應可 commit，且測試綠燈。

### Phase 0：基礎建設（約 0.5 天）

- 開 `feat/fastapi-migration` 分支，保留 `main` 上的 Flask 版可運作
- 建立 `pyproject.toml`，相依改為：`fastapi`、`uvicorn[standard]`、`sqlalchemy[asyncio]`、`asyncpg`、`alembic`、`pydantic-settings`、`pyjwt`、`bcrypt`、`redis`、`fastapi-limiter`、`apscheduler`、`httpx`、`pytest-asyncio`、`testcontainers`、`ruff`
- docker-compose 的 MySQL 換成 Postgres 16
- **驗收**：`docker compose up` 起得來，`uvicorn app.main:app` 回應 `/health`

### Phase 1：資料層（約 1.5 天）

- `core/config.py`、`core/database.py`、`core/redis.py`
- 8 個 model 改寫為 SQLAlchemy 2.0 `Mapped[]` 風格，處理 §5.1 與 §5.5
- Alembic 初始化 + 首版 migration
- **驗收**：`alembic upgrade head` 建出的 schema 與現有 MySQL 一致（用 `alembic revision --autogenerate` 二次執行應產生空 diff）

### Phase 2：認證（約 1.5 天）

- `core/security.py`、`api/deps.py`、`api/v1/auth.py`、`schemas/auth.py`
- 實作 §4 的 refresh 輪替與重用偵測
- **驗收**：`test_auth.py` 改寫並通過，且新增這些案例：過期 token、簽章竄改、`alg=none`、refresh 重用觸發 family 撤銷、登出後 access token 立即失效

### Phase 3：業務路由（約 2.5 天）

依相依性由簡到繁：`menu` → `inventory` → `coupon` → `order` → `payment`

- 每個路由先寫 Pydantic schema，再寫 service，最後寫薄路由
- `order.py` 拆成 `order_service` + `stock_service` + `coupon_service`
- `_deduct_stock()` 的原生 SQL 邏輯原封保留，只改為 `await session.execute(text(...))`
- **驗收**：`test_menu.py` / `test_orders.py` 改寫通過；額外加一個**併發下單測試**（`asyncio.gather` 同時打 N 筆超過庫存的訂單，驗證恰好成功 stock 筆）——這個測試本身就是很好的作品集素材

### Phase 4：周邊（約 1 天）

- `AsyncIOScheduler` 於 lifespan 啟動，加 Redis 鎖
- `fastapi-limiter` 接上，還原原有的 `5 per minute` / `3 per minute` 限制
- 綠界回調改 `Form` + `PlainTextResponse`
- CI 加 Postgres service、ruff；Python 升到 3.12
- `render.yaml` 改 `uvicorn.workers.UvicornWorker`
- **驗收**：CI 全綠；Render 部署成功；`/docs` 可正常 Authorize 並打通一筆訂單

### Phase 5：收尾（約 0.5 天）

- 移除舊 Flask 程式碼與 flasgger docstring
- README 重寫：架構圖、遷移動機、技術決策說明
- 補 `docs/adr/` 記錄關鍵決策（為何自建 JWT、為何統一 Postgres、為何用 async）
- **驗收**：新進者能照 README 在 10 分鐘內把專案跑起來

**合計約 7.5 個工作天**，含測試改寫。若只求跑通不含測試補強，約 4 天。

---

## 8. 驗收總表

遷移完成的判定標準：

- [ ] 全部既有 API 端點行為不變，React 前端不需修改即可運作
- [ ] `alembic revision --autogenerate` 產生空 diff
- [ ] 測試全綠，且覆蓋率不低於遷移前
- [ ] 新增併發下單測試，驗證無超賣
- [ ] 新增 5 項 JWT 安全測試（§Phase 2）
- [ ] CI 通過（pytest + ruff）
- [ ] Render 部署成功
- [ ] `/docs` 的 OpenAPI 文件完整且可互動測試

---

## 9. 作品集敘事重點

遷移完成後，README 與面試可以講的點（依價值排序）：

1. **併發正確性**：原子扣庫存 + Idempotency-Key + 併發測試。這是少數能證明「我想過 race condition」的具體證據，遠比 CRUD 有說服力。
2. **認證深度**：refresh 輪替與重用偵測。能回答「JWT 無狀態怎麼撤銷」「token 被偷怎麼辦」。
3. **技術決策的取捨意識**：ADR 裡寫清楚「知道有 fastapi-users、Auth0，為了 X 理由選擇自建」。這比實作本身更能區隔出資深度。
4. **async 的真實理解**：能講出 bcrypt 阻塞 event loop、lazy loading 在 async 下失效——證明不是只會照抄教學。
5. **既有缺陷的發現與修復**：DateTime 時區、三套資料庫不一致、排程多 worker 重複執行。「我在遷移時發現並修掉了這些」是很強的敘述。
6. **文件即程式碼**：flasgger 60 行 YAML → Pydantic 8 行，且永不漂移。

第 3 點和第 5 點是多數轉職作品集缺少的東西，建議在 README 給它們專門的段落。

---

## 10. 待確認事項

動手前需要你決定：

1. **是否統一為 Postgres**？（§5.3）建議是，但若你的求職目標多為 MySQL 環境，改為統一 MySQL + `aiomysql` 也可以，計畫其餘部分不變。
2. **`MenuItem.orders` / `Order.menu_items` 兩個 association_proxy 目前有被使用嗎**？若無實際用途，async 遷移時建議直接移除。
3. **前端 API 契約可否微調**？例如錯誤回應格式從 `{"message": ...}` 改為 FastAPI 慣例的 `{"detail": ...}`。維持現狀可行，但會需要一個自訂 exception handler。
4. **Python 版本**可否升到 3.12？（目前 CI 為 3.10）
