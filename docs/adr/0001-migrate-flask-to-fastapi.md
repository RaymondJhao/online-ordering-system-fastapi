# 0001. 從 Flask 遷移到 FastAPI

**狀態**：已採用

## 背景

原專案以 Flask 3 實作，功能完整且可運作。促使我重寫的不是「Flask 不好」，
而是三個在維護它的過程中逐漸浮現的具體摩擦：

1. **文件與驗證各寫一次，而且會漂移。**
   `routes/auth.py` 的 login 端點有 60 行手寫的 flasgger YAML docstring，
   佔該函式一半以上篇幅，內容與底下的 `if not email: return 400` 完全獨立。
   任何一邊改了、另一邊忘記改，文件就開始說謊，而沒有任何機制會發現。

2. **輸入驗證淹沒了商業邏輯。**
   `routes/order.py` 有 505 行，其中大量是
   `try: price = float(price) except (TypeError, ValueError): return jsonify(...), 400`。
   四個 helper 都回傳 `(值, error_response)` 二元組，呼叫端要逐一
   `if error_response: return error_response`。真正的訂單邏輯埋在這些分支中間。

3. **權限需求看不見。**
   每個路由開頭一行 `if get_jwt().get("role") != "merchant": return ..., 403`，
   從函式簽章完全看不出這個端點需要什麼權限。

## 考慮過的選項

**維持 Flask，改善現況。**
可以引入 Pydantic 做驗證、改用 apispec 產生文件。這確實能解決前兩點，
但等於在 Flask 上重建 FastAPI 已經內建的東西，且社群慣例支援較弱。

**FastAPI。** 型別註記同時作為驗證規則與 OpenAPI 來源，兩者結構上不可能漂移；
依賴注入讓權限需求出現在函式簽章上。

**Litestar / Django Ninja。** 同樣現代，但生態系與職缺需求都不如 FastAPI。
以轉職為目標時，這一點有實際權重。

## 決定

改用 FastAPI，並趁機做完整重寫而非漸進遷移。

程式碼量沒有變少（`order.py` 505 行 → 路由 168 + service 339 + schema 111），
但職責分開了：路由只負責 HTTP，service 是可獨立測試的商業邏輯，schema 是規格。

## 代價

- **必須理解 async 的陷阱。** lazy loading 在 async 下會拋 `MissingGreenlet`、
  bcrypt 會阻塞 event loop——這些在 Flask 的同步模型下不存在。見 ADR 0002。
- **Flask 生態的現成套件用不了。** Flask-JWT-Extended、Flask-Limiter 都要重找替代方案，
  而 FastAPI 的對應品未必成熟。見 ADR 0003 與 0006。
- **完整重寫的期間比想像長。** 實際約 8 個工作天，主要花在測試改寫而非路由本身。

## 事後回顧

遷移過程中發現了四個原本就存在、但沒被察覺的缺陷：
DateTime 欄位遺失時區、排程宣稱回補庫存卻沒做、拒絕訂單不還庫存、
三套資料庫不一致。這些與 FastAPI 無關，是「為了重寫而逐行讀過一次舊程式碼」的副產品。
