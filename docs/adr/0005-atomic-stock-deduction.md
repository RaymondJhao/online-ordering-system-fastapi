# 0005. 以資料庫層原子操作防止超賣

**狀態**：已採用（沿用自 Flask 版，並修正一個 ORM 快取問題）

## 背景

促銷檔期同一份庫存被兩筆訂單同時搶走，是餐飲／電商後台最典型的併發事故。
直覺的寫法有競態：

```python
item = await db.get(MenuItem, id)
if item.stock >= qty:      # ← 這兩行之間，另一個請求可能讀到同樣的庫存
    item.stock -= qty      #    兩者都通過檢查，結果賣超
```

## 考慮過的選項

**悲觀鎖（`SELECT ... FOR UPDATE`）。**
正確，但要多一次查詢，而且鎖的範圍需要小心管理。

**樂觀鎖（版本欄位）。** 需要重試邏輯，且在高衝突下重試率會很高。

**把條件放進 UPDATE 的 WHERE 子句。**
由資料庫在單一語句內完成「找到庫存足夠的那一列並扣減」：

```sql
UPDATE menu_items SET stock = stock - :qty WHERE id = :id AND stock >= :qty
```

庫存不足時 WHERE 不成立，沒有任何一列被更新，`rowcount` 即為 0。
不需要顯式鎖，也不需要提高隔離級別——UPDATE 本身會對命中的資料列加行鎖，
併發請求排隊執行，後到者看到的是已扣減後的庫存。

## 決定

採用第三種。這也是 Flask 版原本的做法，邏輯正確，遷移時原封保留。

另外加了兩層防護：

- **資料庫 CHECK 約束**（`stock >= 0`）作為第二道防線，
  防止日後有人寫出繞過這條路徑的更新
- **扣減前依 id 排序**，避免兩筆訂單包含相同品項但加鎖順序相反而死結

## 遷移時修正的問題

Flask 版用 `text()` 執行原生 SQL。搬到 async 之後發現一個新問題：
原生 SQL 繞過 ORM，session 的 identity map 仍持有舊的 `stock` 值，
加上本專案的 `expire_on_commit=False`，**同一個 session 之後讀到的是過期資料**。

改用 SQLAlchemy 的 `update()` 建構式並加上 `synchronize_session="fetch"`，
SQL 語意完全相同，但 session 中的物件會同步失效。

## 如何證明它有效

`tests/test_order_concurrency.py` 用獨立連線與交易的 session 並行下單：

- 庫存 5、20 個並行請求 → 恰好成功 5 筆、庫存歸零、只建立 5 筆訂單
- 每筆訂購 2 份、庫存 10、15 個並行請求 → 恰好成功 5 筆
- 需求量刻意超過庫存 → 庫存不會變成負數

**這些測試不能用共用 session 的 fixture。** 那樣所有操作跑在同一筆交易裡，
天然沒有競爭，測了等於沒測。

有效性用突變測試確認過：把原子扣減換回「先讀再判斷再寫」，
4 個測試中有 3 個失敗（20 個請求全部成功，庫存變負）。
