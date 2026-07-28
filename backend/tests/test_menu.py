"""
菜單管理 API 的 pytest 整合測試。

涵蓋三個情境：
1. 商家新增餐點：使用 merchant token 呼叫 POST /api/menu，應成功建立 (201)。
2. RBAC 防護：使用 customer token 呼叫 POST /api/menu，應被擋下 (403)。
3. 上下架切換：使用 merchant token 呼叫 PUT /api/menu/<item_id>，
   驗證 is_active 會正確反轉。
"""

from app.extensions import db
from app.models import MenuItem


def test_merchant_can_create_menu_item(client, init_db, merchant_token):
    """商家使用自己的 token 新增餐點，應回傳 201 並成功寫入資料庫。"""
    response = client.post(
        "/api/menu",
        json={
            "name": "珍珠奶茶",
            "price": 60,
            "description": "測試新增餐點",
            "stock": 30,
        },
        headers={"Authorization": f"Bearer {merchant_token}"},
    )

    assert response.status_code == 201
    body = response.get_json()["menu_item"]
    assert body["name"] == "珍珠奶茶"
    assert body["price"] == 60.0
    assert body["merchant_id"] == init_db["merchant"].id

    # 資料庫裡應確實多了這一筆餐點
    created_item = MenuItem.query.filter_by(name="珍珠奶茶").first()
    assert created_item is not None
    assert created_item.stock == 30


def test_customer_cannot_create_menu_item(client, init_db, customer_token):
    """顧客不具備商家權限，呼叫 POST /api/menu 應被 RBAC 擋下，回傳 403。"""
    response = client.post(
        "/api/menu",
        json={"name": "非法新增的餐點", "price": 100},
        headers={"Authorization": f"Bearer {customer_token}"},
    )

    assert response.status_code == 403

    # 資料庫不應出現這筆餐點
    assert MenuItem.query.filter_by(name="非法新增的餐點").first() is None


def test_merchant_can_toggle_menu_item_active_status(client, init_db, merchant_token):
    """商家呼叫 PUT /api/menu/<item_id> 進行上下架切換，is_active 應正確反轉。"""
    menu_item = init_db["menu_item"]
    original_status = menu_item.is_active  # conftest.py 建立時預設為 True（上架中）

    response = client.put(
        f"/api/menu/{menu_item.id}",
        json={},
        headers={"Authorization": f"Bearer {merchant_token}"},
    )

    assert response.status_code == 200
    assert response.get_json()["menu_item"]["is_active"] == (not original_status)

    # 重新從資料庫撈取，確認狀態已反轉並持久化
    refreshed_item = db.session.get(MenuItem, menu_item.id)
    assert refreshed_item.is_active == (not original_status)
