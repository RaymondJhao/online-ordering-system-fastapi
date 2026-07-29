# Backend — 線上點餐自取系統 API

給後端開發者看的技術文件。專案整體介紹（含前端、架構圖、商業脈絡）請見
[根目錄 README](../README.md)；這份文件只聚焦在 `backend/` 這個 Flask 專案本身：
怎麼跑起來、目錄怎麼分工、資料庫怎麼建、測試怎麼跑。

---

## 技術棧

| 分類 | 技術 |
|---|---|
| 框架 | Flask 3 |
| ORM | SQLAlchemy 2.0（透過 Flask-SQLAlchemy） |
| 資料庫 | MySQL 8（`docker-compose.yml` 內建；`DATABASE_URL` 可換成 PostgreSQL） |
| 認證 | Flask-JWT-Extended（JWT）+ Flask-Bcrypt（密碼雜湊） |
| 限流 | Flask-Limiter（storage 優先接 Redis，連不到才 fallback 回 in-memory） |
| 背景任務 | APScheduler（逾時未付款訂單自動取消） |
| 金流 | 綠界科技 ECPay（測試環境） |
| API 文件 | Flasgger（Swagger UI，路徑 `/apidocs`） |
| 測試 | pytest + pytest-flask（SQLite in-memory） |

---

## 目錄結構

```
backend/
├── app.py                  # 應用程式進入點：建立 app、掛載 Swagger、db.create_all()、app.run()
├── reset_db.py              # 開發用：清空並依目前 models.py 重建所有資料表
├── seed_menu_items.py       # 開發用：灌入測試商家／顧客／餐點／優惠券與情境訂單
├── docker-compose.yml       # 本機 MySQL + Redis
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py         # create_app() 工廠函式：init 各 extension、註冊 blueprint、啟動排程
│   ├── config.py           # Config：從環境變數讀 SECRET_KEY / JWT_SECRET_KEY / DATABASE_URL
│   ├── extensions.py       # db / bcrypt / jwt / limiter 等 Flask extension 實例（避免循環匯入）
│   ├── models.py           # 所有 SQLAlchemy Model：Customer、Merchant、MenuItem、Order、
│   │                        # OrderItem、Coupon、TokenBlocklist、IdempotencyRecord
│   ├── tasks.py             # APScheduler 背景任務：逾時未付款訂單自動取消、釋出庫存
│   ├── routes/              # 依資源拆分的 Blueprint，每個檔案對應一組 API
│   │   ├── auth.py          # 註冊 / 登入 / 登出（JWT 簽發與 Blocklist）
│   │   ├── menu.py          # 菜單 CRUD
│   │   ├── inventory.py     # 庫存管理（商家後台用）
│   │   ├── coupon.py        # 優惠券 CRUD
│   │   ├── order.py         # 下單、訂單列表、狀態機轉移（本專案核心業務邏輯）
│   │   └── payment.py       # 綠界 ECPay 建立付款 / callback 驗簽
│   └── utils/
│       └── ecpay.py         # CheckMacValue 簽章演算法（金流簽章的唯一真實來源）
└── tests/
    ├── conftest.py           # 共用 fixtures：app / client / init_db（假資料）/ 各角色 JWT token
    ├── test_auth.py
    ├── test_menu.py
    └── test_orders.py        # 涵蓋下單、庫存扣減、冪等性、狀態機防護等核心情境
```

**分工原則**：`routes/` 只處理 HTTP 層（參數驗證、權限檢查、組裝回應），
真正的商業規則（狀態機轉移表、原子扣庫存 SQL、金流簽章）都收斂在
`routes/order.py`、`utils/ecpay.py` 這類單一入口，避免規則散落在多處各自維護一份。

---

## 本地端啟動指南

### 1. 建立與啟動虛擬環境

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
```

### 3. 啟動 MySQL / Redis

```bash
docker compose up -d
```

### 4. 設定環境變數

複製 `.env.example` 為 `.env`，依需要調整：

```
SECRET_KEY=change-me
JWT_SECRET_KEY=change-me
DATABASE_URL=mysql+pymysql://YOUR_DB_USER:YOUR_DB_PASSWORD@localhost:3306/online_ordering_system
REDIS_URL=redis://localhost:6379/0

# 綠界（ECPay）測試環境設定 — 以下為官方公開的測試用金鑰，非正式上線金鑰
ECPAY_MERCHANT_ID=2000132
ECPAY_HASH_KEY=5294y06JbISpM5x9
ECPAY_HASH_IV=v77hoKGq4kWxNNIS
ECPAY_RETURN_URL=https://your-ngrok-domain.ngrok-free.app/api/payment/ecpay/callback
```

`config.py` 會用 `SECRET_KEY` / `JWT_SECRET_KEY` 分別簽 Flask session 與 JWT；
`DATABASE_URL` 沒設定時會 fallback 到本機 SQLite 檔案，方便沒裝 MySQL 也能先跑起來。

### 5. 啟動伺服器

```bash
python app.py
```

- API 預設跑在 `http://localhost:5000`
- Swagger UI：`http://localhost:5000/apidocs`

---

## 資料庫與測試資料腳本

### 重建資料表結構：`reset_db.py`

修改過 `models.py`（新增欄位、改 Enum 等）之後，直接清空重建最快：

```bash
python reset_db.py
```

執行前會要求輸入 `yes` 二次確認，因為這會 `drop_all()` 清空 MySQL 裡**所有**資料表再
`create_all()` 重建。只適合開發環境；正式環境的 schema 變更需要走 Alembic migration，
不能用這支腳本。

### 灌入測試資料：`seed_menu_items.py`

```bash
python seed_menu_items.py                    # 使用預設測試商家帳號
python seed_menu_items.py your@merchant.com  # 指定其他商家帳號
```

會建立（或沿用既有的）：
- 一個測試商家帳號（預設 `merchant@test.com` / `test1234`）
- 一個測試顧客帳號（`customer@test.com` / `test1234`）
- 三個菜單品項（含一個庫存 0、已下架的品項，方便測「售完」畫面）
- 一張固定折抵優惠券 `OPEN888`
- **三筆情境訂單**：待接單（PENDING/UNPAID）、已拒單附原因（REJECTED）、
  已完成待退款（COMPLETED/PAID），方便不用手動操作就能直接測前端各種狀態畫面

商家／顧客／餐點／優惠券都是 get-or-create，可重複執行不會撞
`IntegrityError`；情境訂單則每次執行都會新增一批，方便反覆測試接單流程。

---

## 測試指南

```bash
pytest -v
```

測試一律連到記憶體內 SQLite（見 `tests/conftest.py` 的 `TestConfig`），**不會**去動
`.env` 裡設定的開發用 MySQL，可以放心重複執行。`RATELIMIT_ENABLED = False`
也一併在測試環境關閉，避免測試案例互相因為 rate limit 卡住。

目前涵蓋的核心情境（詳見 `tests/test_orders.py`）：
- 下單成功（含優惠券折抵、預約時間、庫存正確扣減）
- 庫存不足時擋單
- Idempotency-Key 防止同一使用者重複建單
- Idempotency-Key 依 `user_id` 隔離，不同使用者用同一把 key 不會互相看到彼此的訂單
- 訂單狀態機防止非法跳躍轉移（回傳 409）

CI（`.github/workflows/backend-ci.yml`）會在 push / PR 到 `main` 時自動安裝依賴並執行
`pytest`。

---

## 金流串接備註（ECPay）

- **CheckMacValue 簽章邏輯**：全部收斂在 [`app/utils/ecpay.py`](app/utils/ecpay.py) 的
  `generate_check_mac_value()`，是唯一計算/驗證簽章的地方。步驟：依 key 字母排序 → 前後
  夾上 `HashKey` / `HashIV` → URL encode 轉小寫 → 修正 `.NET UrlEncode` 與 Python
  `quote_plus` 在 `-`、`_`、`.`、`!`、`*`、`(`、`)` 這幾個字元上的編碼差異 → SHA256 →
  轉大寫。建立付款（[`app/routes/payment.py`](app/routes/payment.py) 的 `checkout()`）與
  驗證 callback（`ecpay_callback()`）都呼叫同一個函式，確保雙邊算法不會不一致。

- **Webhook（ReturnURL）運作方式**：`POST /api/payment/callback` 是綠界背景伺服器直接
  呼叫的端點，沒有登入者、不能用 JWT 驗證身分，改用 `CheckMacValue` 驗證這筆通知確實
  來自綠界且內容未被竄改（驗不過直接回 `0|Error`）。訂單編號透過 `CustomField1`
  帶回（建立付款時塞入 `order.id`），不依賴解析 `MerchantTradeNo` 這種容易產生歧義的
  字串。更新付款狀態前會先檢查 `payment_status == UNPAID` 才寫入 `PAID`，天然具備
  冪等性，可以安全承受綠界的重複通知重試。

- **本機測試 Webhook**：`ECPAY_RETURN_URL` 必須是外網可以打進來的網址，本機開發建議用
  `ngrok http 5000` 開一條通道，把 `.env` 裡的 `ECPAY_RETURN_URL` 換成 ngrok 給的網址後
  重啟服務，才能在測試環境走完整的刷卡 → callback 流程。

- `.env.example` 裡的 `ECPAY_MERCHANT_ID` / `ECPAY_HASH_KEY` / `ECPAY_HASH_IV` 是綠界官方
  公開文件上的測試環境金鑰，不是任何人的正式密鑰外洩；正式上線需替換成商店後台申請的
  正式金鑰，並改走正式環境的 Checkout URL。
