# 0002. 資料層全面改為 async

**狀態**：已採用

## 背景

FastAPI 支援兩種寫法：`async def` 路由跑在事件迴圈上，`def` 路由則被丟到
threadpool 執行。後者可以直接沿用同步的 SQLAlchemy，改動最小。

## 考慮過的選項

**維持同步 SQLAlchemy，路由寫成 `def`。**
遷移成本最低，測試幾乎不用動。但這會讓「為什麼要用 FastAPI」變得難以回答——
如果每個請求都佔用一條執行緒，效能模型跟 Flask 沒有本質差別。

**全面 async。** 需要 asyncpg、AsyncSession、httpx AsyncClient 測試，
工作量約兩倍。

## 決定

全面 async。這是 FastAPI 的標準用法，也是真正理解這個框架的必經之路。

## 代價與踩過的坑

這個決定的代價不是「多寫程式碼」，而是三個錯誤訊息不直觀的陷阱：

**1. Lazy loading 會直接拋 `MissingGreenlet`。**
同步下存取未載入的關聯會自動發 SQL，async 下則會爆炸。所有需要關聯資料的查詢
都必須明確 `selectinload`。原本 models 裡的兩個 `association_proxy` 在 async 下
特別麻煩，確認整個專案都沒用到之後直接移除。

**2. `expire_on_commit` 預設值會害人。**
預設 True 會讓 commit 後的屬性存取觸發隱式重新查詢，在 async 下同樣拋
`MissingGreenlet`。典型症狀是 service commit 之後回傳 order，路由層讀 `order.id`
時整個請求失敗。設為 False 解決。

**3. CPU 密集操作會卡住所有請求。**
bcrypt 雜湊需要 100~300ms 的純運算。在 `async def` 裡直接呼叫會阻塞整個
event loop——這比 Flask 更糟，因為 Flask 至少每個 worker 各處理一個請求。
必須用 `anyio.to_thread.run_sync` 丟到 threadpool。

上述三點都寫成了測試（`tests/test_models.py`、`tests/test_auth_security.py`），
包括一個用 `pytest.raises(MissingGreenlet)` 證明陷阱確實存在的測試。

**附帶發現：覆蓋率報告會失真。**
SQLAlchemy 的 async 以 greenlet 實作，coverage.py 預設追蹤器在 greenlet 切換後
會跟丟 frame，導致「await 之後的每一行」被算成未覆蓋。加上
`concurrency = ["thread", "greenlet"]` 後，數字從 87% 更正為 94%。

## 什麼情況下這個決定會是錯的

如果這個系統的瓶頸是 CPU（大量計算）而非 I/O 等待，async 帶來的複雜度就不划算。
以點餐系統來說，絕大多數時間花在等資料庫回應，async 是合適的。
