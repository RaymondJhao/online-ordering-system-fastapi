# Frontend — 線上點餐自取系統

給前端開發者看的技術文件。專案整體介紹（含後端、架構圖、商業脈絡）請見
[根目錄 README](../README.md)；這份文件只聚焦在 `frontend/` 這個 React 專案本身：
怎麼跑起來、目錄怎麼分工、核心模組的設計取捨、測試怎麼跑。

---

## 技術棧

| 分類 | 技術 |
|---|---|
| 建構工具 | Vite 7 |
| UI 框架 | React 19（無 TypeScript） |
| 樣式 | Tailwind CSS 3 |
| 路由 | React Router 7 |
| HTTP client | Axios（全域 interceptor 自動帶 JWT） |
| 測試 | Vitest + React Testing Library + jsdom |
| Icon | lucide-react |
| Lint | oxlint |

沒有導入 Redux / Zustand 之類的全域狀態管理庫：目前唯一需要跨頁面共用、
且需要持久化的狀態只有購物車，用 React Context + `localStorage` 就足夠，
不需要為此引入額外的狀態管理框架。

---

## 核心模組說明

### 顧客端流程

| 頁面 | 路徑 | 職責 |
|---|---|---|
| `pages/CustomerMenu.jsx` | `/` | 瀏覽菜單、加入購物車（免登入即可瀏覽與加購） |
| `pages/Checkout.jsx` | `/checkout` | 選擇付款方式（線上刷卡／現場現金）、填寫預約取餐時間、套用優惠券、送出訂單 |
| `pages/CustomerOrders.jsx` | `/orders` | 查詢歷史訂單與目前訂單狀態（含拒單原因顯示） |
| `pages/Auth.jsx` | `/auth` | 顧客／商家共用的登入註冊頁 |

**免登入購物車（`context/CartContext.jsx`）**：購物車狀態用 React Context 提供給全站，
並在 `useEffect` 監聽 `cart` 變化時同步寫入 `localStorage`（key: `shopping_cart`），
初始化時則反向從 `localStorage` 讀回。這代表顧客瀏覽菜單、加入商品**不需要先登入**，
重新整理頁面或關掉分頁再回來，購物車內容也不會消失；只有在 `Checkout.jsx` 實際送出
訂單時才會要求登入身分（因為訂單必須綁定 `customer_id`）。`clearCart()` 會同時清空
記憶體狀態與 `localStorage`，避免下單成功後舊購物車殘留。

### 商家大螢幕（Merchant Dashboard）

`pages/MerchantDashboard.jsx` 是商家後台的殼層，負責分頁切換與跨分頁共用的庫存資料，
實際功能拆到 `components/merchant/` 底下四個獨立元件：

| 元件 | 對應分頁 | 職責 |
|---|---|---|
| `OrderList.jsx` | 訂單看板 | 顯示訂單、依狀態機切換訂單狀態（接單／拒單／出餐／完成／退款） |
| `InventoryPanel.jsx` | 庫存查詢 | 新增／編輯菜單品項與庫存數量 |
| `CouponPanel.jsx` | 優惠券管理 | 建立／啟用停用優惠券 |
| `ManualOrderForm.jsx` | 手動建單（POS） | 商家在大螢幕手動輸入現場／電話訂單，沒有對應顧客帳號 |

- **POS 機高對比 UI**：整個後台走深色底（`bg-gray-900`）+ 高對比文字配色，按鈕一律
  `min-h-[52px]`、`text-lg font-bold`，是刻意針對「店員可能戴著手套、站著操作觸控螢幕、
  廚房環境光線不佳」這種實際 POS 使用情境設計的，不是單純的深色主題偏好。
- **防誤觸機制**：任何不可逆的操作——拒單、作廢（CANCELLED）、退款（REFUNDED）——
  都不會被單一次點擊直接執行，而是先彈出 `DangerConfirmModal`（`OrderList.jsx`）要求
  二次確認，拒單還會額外用 `RejectReasonModal` 強制輸入原因（後端 API 也會擋掉沒有
  `reject_reason` 的拒單請求，前後端雙重防呆）。
- **訂單狀態機切換**：`OrderList.jsx` 依照當前訂單狀態，只渲染後端 `ALLOWED_TRANSITIONS`
  允許的下一步操作按鈕（例如 `PENDING` 只會看到「接單」「拒單」），避免商家在 UI 上
  誤觸一個後端一定會擋掉的非法狀態轉移，減少無意義的錯誤回應。
- **庫存資料由父層共用**：`MerchantDashboard.jsx` 把 `fetchInventory()` 提升到自己身上，
  「庫存查詢」與「手動建單」兩個分頁共用同一份餐點清單，切換分頁不會重複打 API，
  POS 建單完成後也能立刻看到扣減後的最新庫存。

---

## 本地端啟動指南

### 1. 安裝依賴

```bash
cd frontend
npm install
```

### 2. 啟動開發伺服器

```bash
npm run dev
```

預設跑在 `http://localhost:5173`。

### 3. Vite Proxy 設定（解決 CORS）

`vite.config.js` 內設定了開發伺服器 proxy：

```js
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:5000',
      changeOrigin: true,
    },
  },
},
```

前端程式碼裡打 API 一律用相對路徑（例如 `axios.get('/api/inventory')`，見
`src/lib/axios.js` 與各頁面元件），開發模式下 Vite dev server 會把所有 `/api/*`
請求原樣轉發到本機 Flask 後端（預設 `http://localhost:5000`）。這代表：

- 瀏覽器實際上只跟 `localhost:5173`（前端自己）通訊，不會直接打
  `localhost:5000`，所以**不會觸發瀏覽器的 CORS 檢查**，後端也不需要另外裝
  `flask-cors` 處理開發環境的跨來源問題。
- 如果後端沒有跑在預設的 5000 port，記得同步修改這裡的 `target`。
- 正式環境（`npm run build` 產出的靜態檔案）不會經過 Vite dev server，需要在
  反向代理（Nginx 等）或後端本身處理 `/api` 路由與 CORS。

### 4. 登入測試帳號

前端本身不建立帳號資料，請先參考
[`backend/README.md`](../backend/README.md) 執行 `seed_menu_items.py` 灌入測試商家／
顧客帳號後，再從 `/auth` 頁面登入。

---

## 資料夾結構

```
frontend/
├── vite.config.js          # Vite 設定：React 插件、/api proxy、Vitest 設定
├── tailwind.config.js
├── src/
│   ├── main.jsx             # React 進入點，掛載 <App />
│   ├── App.jsx               # 路由表（React Router），最外層包 <CartProvider>
│   ├── context/
│   │   └── CartContext.jsx   # 購物車狀態 + localStorage 同步
│   ├── lib/
│   │   └── axios.js          # 全域 axios interceptor：自動帶入 JWT Authorization header
│   ├── pages/                # 每個路由對應一支檔案，負責資料抓取與頁面組裝
│   │   ├── CustomerMenu.jsx
│   │   ├── Checkout.jsx
│   │   ├── CustomerOrders.jsx
│   │   ├── Auth.jsx
│   │   └── MerchantDashboard.jsx   # 商家後台殼層（分頁切換 + 共用庫存資料）
│   ├── components/
│   │   └── merchant/          # MerchantDashboard 底下拆出的可獨立測試子元件
│   │       ├── OrderList.jsx
│   │       ├── InventoryPanel.jsx
│   │       ├── CouponPanel.jsx
│   │       └── ManualOrderForm.jsx
│   └── tests/
│       ├── setup.js           # Vitest 全域設定（jsdom 環境、testing-library matcher）
│       └── Cart.test.jsx      # 元件測試
```

**分工原則**：`pages/` 只負責「這個路由需要什麼資料、要組合哪些元件」；
可重複利用或邏輯複雜到值得獨立測試的 UI（例如商家後台四個分頁），拆到
`components/` 底下，讓 `pages/MerchantDashboard.jsx` 保持單純的殼層角色，
不會隨著功能增加又長成一支上千行的檔案。

---

## 前端測試

```bash
npm run test
```

實際執行的是 `vitest run`（見 `package.json` 的 `test` script），測試環境設定在
`vite.config.js` 的 `test` 區塊：`environment: 'jsdom'` 讓 Vitest 在 Node 裡模擬瀏覽器
DOM，`setupFiles: ['./src/tests/setup.js']` 載入 `@testing-library/jest-dom` 的自訂
matcher（例如 `toBeInTheDocument()`）。

開發時如果要邊改邊看測試結果，可以用 watch 模式：

```bash
npx vitest
```

目前測試覆蓋面還在起步階段（詳見根目錄 README 的「後續規劃」），優先開發原則是：
**跟商業邏輯高度相關的元件（購物車計算、表單驗證）優先寫測試**，單純的展示型元件
（例如純渲染 props 的卡片元件）優先度較低。
