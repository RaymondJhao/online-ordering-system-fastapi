"""菜單、庫存與優惠券端點。"""

from httpx import AsyncClient

from tests.conftest import auth_headers

# ---------------------------------------------------------------------------
# 菜單
# ---------------------------------------------------------------------------


async def test_菜單為公開端點不需登入(client: AsyncClient, merchant_menu_item: dict) -> None:
    response = await client.get("/api/menu")

    assert response.status_code == 200
    assert any(item["id"] == merchant_menu_item["id"] for item in response.json())


async def test_下架的餐點不會出現在公開菜單(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    await client.put(
        f"/api/menu/{merchant_menu_item['id']}",
        json={"is_active": False},
        headers=auth_headers(merchant_session),
    )

    response = await client.get("/api/menu")
    assert all(item["id"] != merchant_menu_item["id"] for item in response.json())


async def test_顧客不能新增餐點(client: AsyncClient, customer_session: dict) -> None:
    response = await client.post(
        "/api/menu",
        json={"name": "偷加的餐點", "price": "100.00", "stock": 1},
        headers=auth_headers(customer_session),
    )
    assert response.status_code == 403


async def test_價格為負數會被擋下(client: AsyncClient, merchant_session: dict) -> None:
    """舊版需要手寫 `try: float(price) except` 與 `if price <= 0`，
    這裡由 Field(gt=0) 的型別約束處理，並自動反映在 OpenAPI 文件上。"""
    response = await client.post(
        "/api/menu",
        json={"name": "負價餐點", "price": "-10.00", "stock": 1},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 422


async def test_庫存為負數會被擋下(client: AsyncClient, merchant_session: dict) -> None:
    response = await client.post(
        "/api/menu",
        json={"name": "負庫存", "price": "10.00", "stock": -5},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 422


async def test_部分更新只改有帶的欄位(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await client.put(
        f"/api/menu/{merchant_menu_item['id']}",
        json={"price": "150.00"},
        headers=auth_headers(merchant_session),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "150.00"
    assert body["name"] == merchant_menu_item["name"], "沒帶的欄位不應被改動"
    assert body["stock"] == merchant_menu_item["stock"]


async def test_空_body_會切換上下架狀態(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """沿用舊版行為，遷移階段不改變既有前端的使用方式。"""
    response = await client.put(
        f"/api/menu/{merchant_menu_item['id']}",
        json={},
        headers=auth_headers(merchant_session),
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is not merchant_menu_item["is_active"]


async def test_不能修改別人的餐點(client: AsyncClient, merchant_menu_item: dict) -> None:
    other = await client.post(
        "/api/auth/register",
        json={
            "role": "merchant",
            "name": "別間店",
            "email": "other-shop@test.com",
            "password": "password123",
        },
    )
    assert other.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"role": "merchant", "email": "other-shop@test.com", "password": "password123"},
    )

    response = await client.put(
        f"/api/menu/{merchant_menu_item['id']}",
        json={"price": "1.00"},
        headers=auth_headers(login.json()),
    )
    assert response.status_code == 403


async def test_庫存清單包含已下架品項(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    await client.put(
        f"/api/menu/{merchant_menu_item['id']}",
        json={"is_active": False},
        headers=auth_headers(merchant_session),
    )

    response = await client.get("/api/inventory", headers=auth_headers(merchant_session))

    assert response.status_code == 200
    assert any(item["id"] == merchant_menu_item["id"] for item in response.json())


# ---------------------------------------------------------------------------
# 優惠券
# ---------------------------------------------------------------------------


async def test_建立優惠券(client: AsyncClient, merchant_session: dict) -> None:
    response = await client.post(
        "/api/coupons",
        json={"code": "OPEN888", "discount_type": "FIXED", "discount_value": 50},
        headers=auth_headers(merchant_session),
    )

    assert response.status_code == 201
    assert response.json()["code"] == "OPEN888"


async def test_重複優惠碼回_409(client: AsyncClient, merchant_session: dict) -> None:
    payload = {"code": "DUP123", "discount_type": "FIXED", "discount_value": 10}
    await client.post("/api/coupons", json=payload, headers=auth_headers(merchant_session))

    response = await client.post(
        "/api/coupons", json=payload, headers=auth_headers(merchant_session)
    )
    assert response.status_code == 409


async def test_百分比折扣超過_100_會被擋下(client: AsyncClient, merchant_session: dict) -> None:
    """跨欄位規則：discount_value 的合法上限取決於 discount_type。"""
    response = await client.post(
        "/api/coupons",
        json={"code": "BAD", "discount_type": "PERCENTAGE", "discount_value": 150},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 422


async def test_折扣值必須為正整數(client: AsyncClient, merchant_session: dict) -> None:
    response = await client.post(
        "/api/coupons",
        json={"code": "ZERO", "discount_type": "FIXED", "discount_value": 0},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 422


async def test_顧客不能查看優惠券清單(client: AsyncClient, customer_session: dict) -> None:
    response = await client.get("/api/coupons", headers=auth_headers(customer_session))
    assert response.status_code == 403
