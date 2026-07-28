"""
訂單相關 API 的 pytest 整合測試。

涵蓋三個情境：
1. 成功建立訂單：驗證預約時間、優惠券折抵、庫存扣減是否正確。
2. 高併發防護：同一把 Idempotency-Key 重複送出下單請求時，
   系統應攔截並回傳第一次的結果，不可重複扣庫存 / 重複建單。
3. 狀態機防禦：商家不可將 PENDING 訂單直接改為 COMPLETED，應回傳 HTTP 409。
"""

from app.extensions import db
from app.models import MenuItem, Order


def test_create_order_success_with_pickup_time_and_coupon(client, init_db, customer_token):
    """成功建立訂單：套用優惠券折抵 + 指定預約時間，且庫存要正確扣減。"""
    merchant = init_db["merchant"]
    menu_item = init_db["menu_item"]
    pickup_time = "2026-07-29T18:30:00"  # 預約時間（ISO 8601，不含時區以避免資料庫方言差異）

    response = client.post(
        "/api/orders",
        json={
            "merchant_id": merchant.id,
            "items": [{"menu_item_id": menu_item.id, "quantity": 2}],
            "coupon_code": "OPEN888",
            "pickup_time": pickup_time,
        },
        headers={"Authorization": f"Bearer {customer_token}"},
    )

    assert response.status_code == 201
    order = response.get_json()["order"]

    # 餐點單價 120 元 x 2 個 = 240 元，扣掉 OPEN888 固定折抵 50 元 = 190 元
    assert order["total_price"] == 190.0
    assert order["discount_amount"] == 50
    assert order["coupon_id"] == init_db["coupon"].id
    assert order["status"] == "PENDING"
    assert order["pickup_time"].startswith("2026-07-29T18:30:00")

    # 驗證庫存確實從 50 被扣到 48（原始庫存 - 購買數量）
    refreshed_menu_item = db.session.get(MenuItem, menu_item.id)
    assert refreshed_menu_item.stock == 48


def test_create_order_fails_when_stock_insufficient(client, init_db, customer_token):
    """庫存不足時應回傳 400，且不能建立訂單、也不能扣庫存。"""
    merchant = init_db["merchant"]
    menu_item = init_db["menu_item"]

    response = client.post(
        "/api/orders",
        json={
            "merchant_id": merchant.id,
            "items": [{"menu_item_id": menu_item.id, "quantity": 9999}],
        },
        headers={"Authorization": f"Bearer {customer_token}"},
    )

    assert response.status_code == 400
    assert Order.query.count() == 0

    refreshed_menu_item = db.session.get(MenuItem, menu_item.id)
    assert refreshed_menu_item.stock == 50  # 庫存維持不變


def test_idempotency_key_prevents_duplicate_order(client, init_db, customer_token):
    """高併發防護：顧客網路逾時或手滑雙擊送出，帶著相同的 Idempotency-Key
    重複呼叫下單 API 時，第二次請求應被系統攔截，直接回傳第一次的訂單結果，
    絕對不能重複扣庫存或建立第二筆訂單。"""
    merchant = init_db["merchant"]
    menu_item = init_db["menu_item"]
    headers = {
        "Authorization": f"Bearer {customer_token}",
        "Idempotency-Key": "duplicate-key-123",
    }
    payload = {
        "merchant_id": merchant.id,
        "items": [{"menu_item_id": menu_item.id, "quantity": 2}],
    }

    first_response = client.post("/api/orders", json=payload, headers=headers)
    assert first_response.status_code == 201
    first_order_id = first_response.get_json()["order"]["id"]

    # 帶著同一把 Idempotency-Key 再送一次同樣的下單請求
    second_response = client.post("/api/orders", json=payload, headers=headers)

    # 第二次請求應被攔截：回傳 200（而非再建立一筆新訂單的 201），
    # 且訂單內容跟第一次完全相同
    assert second_response.status_code == 200
    second_order_id = second_response.get_json()["order"]["id"]
    assert second_order_id == first_order_id

    # 全資料庫應該只有這一筆訂單，庫存也只被扣一次（50 - 2 = 48，而不是 46）
    assert Order.query.count() == 1
    refreshed_menu_item = db.session.get(MenuItem, menu_item.id)
    assert refreshed_menu_item.stock == 48


def test_merchant_cannot_skip_status_directly_to_completed(
    client, init_db, customer_token, merchant_token
):
    """狀態機防禦：訂單建立後預設為 PENDING，合法的下一步只有
    ACCEPTED 或 REJECTED；商家不可以把 PENDING 訂單直接改成 COMPLETED，
    違反狀態機規則時應回傳 HTTP 409，且訂單狀態不可被更動。"""
    merchant = init_db["merchant"]
    menu_item = init_db["menu_item"]

    create_response = client.post(
        "/api/orders",
        json={
            "merchant_id": merchant.id,
            "items": [{"menu_item_id": menu_item.id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert create_response.status_code == 201
    order_id = create_response.get_json()["order"]["id"]

    status_response = client.put(
        f"/api/orders/{order_id}/status",
        json={"status": "COMPLETED"},
        headers={"Authorization": f"Bearer {merchant_token}"},
    )

    assert status_response.status_code == 409
    assert "PENDING" in status_response.get_json()["message"]

    # 訂單狀態必須維持在 PENDING，不可被非法轉移更動
    order = db.session.get(Order, order_id)
    assert order.status.value == "PENDING"
