"""訂單端點：金額計算、庫存、冪等、狀態機與權限隔離。"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import auth_headers


async def _place_order(
    client: AsyncClient,
    customer_session: dict,
    merchant_id: int,
    menu_item_id: int,
    quantity: int = 1,
    **extra,
):
    payload = {
        "merchant_id": merchant_id,
        "items": [{"menu_item_id": menu_item_id, "quantity": quantity}],
        **extra,
    }
    return await client.post("/api/orders", json=payload, headers=auth_headers(customer_session))


# ---------------------------------------------------------------------------
# 金額計算
# ---------------------------------------------------------------------------


async def test_下單成功並由後端計算總價(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"], 2
    )

    assert response.status_code == 201
    body = response.json()
    assert body["total_price"] == "240.00", "120 × 2"
    assert body["status"] == "PENDING"
    assert body["payment_status"] == "UNPAID"
    assert body["items"][0]["name"] == "招牌漢堡"


async def test_前端傳來的金額欄位不會被採用(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """總價一律由後端依資料庫單價重算。

    schema 沒有宣告 total_price 欄位，多傳的欄位會被忽略而非採信——
    這是「不接受前端金額」最直接的保證。
    """
    response = await client.post(
        "/api/orders",
        json={
            "merchant_id": merchant_session["user"]["id"],
            "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
            "total_price": "1.00",
            "discount_amount": 999,
        },
        headers=auth_headers(customer_session),
    )

    assert response.status_code == 201
    assert response.json()["total_price"] == "120.00"
    assert response.json()["discount_amount"] == 0


async def test_固定金額優惠券折抵(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    await client.post(
        "/api/coupons",
        json={"code": "MINUS50", "discount_type": "FIXED", "discount_value": 50},
        headers=auth_headers(merchant_session),
    )

    response = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        1,
        coupon_code="MINUS50",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["discount_amount"] == 50
    assert body["total_price"] == "70.00"


async def test_折扣不會讓總價變成負數(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """折抵金額大於原價時，折扣以原價為上限。

    沒有這個上限，訂單金額會變成負數，送進金流會直接被拒絕，
    或更糟——被當成負數的請款金額。
    """
    await client.post(
        "/api/coupons",
        json={"code": "HUGE", "discount_type": "FIXED", "discount_value": 99999},
        headers=auth_headers(merchant_session),
    )

    response = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        1,
        coupon_code="HUGE",
    )

    assert response.status_code == 201
    assert response.json()["total_price"] == "0.00"


async def test_不存在的優惠碼回_400(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        coupon_code="NOPE",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 庫存
# ---------------------------------------------------------------------------


async def test_庫存不足時整筆訂單失敗(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"], 999
    )

    assert response.status_code == 409
    assert "庫存不足" in response.json()["detail"]

    inventory = await client.get("/api/inventory", headers=auth_headers(merchant_session))
    item = next(i for i in inventory.json() if i["id"] == merchant_menu_item["id"])
    assert item["stock"] == 50, "失敗的訂單不可以扣到庫存"


async def test_下單成功會扣減庫存(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"], 3
    )

    inventory = await client.get("/api/inventory", headers=auth_headers(merchant_session))
    item = next(i for i in inventory.json() if i["id"] == merchant_menu_item["id"])
    assert item["stock"] == 47


async def test_訂單被拒絕時庫存會還回去(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """舊版沒有這個行為：拒絕訂單只改狀態，已扣的庫存不會回補，
    等於商家每拒絕一筆訂單就永久少掉那些庫存。"""
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"], 5
    )
    order_id = order.json()["id"]

    await client.put(
        f"/api/orders/{order_id}/status",
        json={"status": "REJECTED", "reject_reason": "備料不足"},
        headers=auth_headers(merchant_session),
    )

    inventory = await client.get("/api/inventory", headers=auth_headers(merchant_session))
    item = next(i for i in inventory.json() if i["id"] == merchant_menu_item["id"])
    assert item["stock"] == 50, "被拒絕的訂單應釋放庫存"


# ---------------------------------------------------------------------------
# 冪等性
# ---------------------------------------------------------------------------


async def test_相同_Idempotency_Key_不會重複建單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """使用者連點兩次送出、或客戶端逾時重試時的防護。"""
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 2}],
    }
    headers = {**auth_headers(customer_session), "Idempotency-Key": "same-key-123"}

    first = await client.post("/api/orders", json=payload, headers=headers)
    second = await client.post("/api/orders", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"], "應回放同一筆訂單"

    inventory = await client.get("/api/inventory", headers=auth_headers(merchant_session))
    item = next(i for i in inventory.json() if i["id"] == merchant_menu_item["id"])
    assert item["stock"] == 48, "庫存只能被扣一次"


async def test_不同_Idempotency_Key_會建立兩筆訂單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
    }
    base = auth_headers(customer_session)

    first = await client.post(
        "/api/orders", json=payload, headers={**base, "Idempotency-Key": "k1"}
    )
    second = await client.post(
        "/api/orders", json=payload, headers={**base, "Idempotency-Key": "k2"}
    )

    assert first.json()["id"] != second.json()["id"]


# ---------------------------------------------------------------------------
# 輸入驗證
# ---------------------------------------------------------------------------


async def test_空的_items_會被擋下(
    client: AsyncClient, customer_session: dict, merchant_session: dict
) -> None:
    response = await client.post(
        "/api/orders",
        json={"merchant_id": merchant_session["user"]["id"], "items": []},
        headers=auth_headers(customer_session),
    )
    assert response.status_code == 422


async def test_數量必須為正整數(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"], 0
    )
    assert response.status_code == 422


async def test_取餐時間不可為過去(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    response = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        pickup_time=past,
    )
    assert response.status_code == 422


async def test_未來的取餐時間可接受(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        pickup_time=future,
    )
    assert response.status_code == 201


async def test_不存在的商家回_404(
    client: AsyncClient, customer_session: dict, merchant_menu_item: dict
) -> None:
    response = await _place_order(client, customer_session, 999999, merchant_menu_item["id"])
    assert response.status_code == 404


async def test_跨商家的餐點無法一起下單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """訂單只能包含指定商家的餐點。

    沒有這道檢查，顧客可以把 A 店的便宜餐點掛到 B 店的訂單上。
    """
    await client.post(
        "/api/auth/register",
        json={
            "role": "merchant",
            "name": "別間店",
            "email": "shop-b@test.com",
            "password": "password123",
        },
    )
    login = await client.post(
        "/api/auth/login",
        json={"role": "merchant", "email": "shop-b@test.com", "password": "password123"},
    )
    other_item = await client.post(
        "/api/menu",
        json={"name": "別店餐點", "price": "10.00", "stock": 10},
        headers=auth_headers(login.json()),
    )

    response = await client.post(
        "/api/orders",
        json={
            "merchant_id": merchant_session["user"]["id"],
            "items": [
                {"menu_item_id": merchant_menu_item["id"], "quantity": 1},
                {"menu_item_id": other_item.json()["id"], "quantity": 1},
            ],
        },
        headers=auth_headers(customer_session),
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 權限
# ---------------------------------------------------------------------------


async def test_商家不能用顧客端點下單(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await client.post(
        "/api/orders",
        json={
            "merchant_id": merchant_session["user"]["id"],
            "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
        },
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 403


async def test_商家建立的現場訂單沒有顧客(
    client: AsyncClient, merchant_session: dict, merchant_menu_item: dict
) -> None:
    response = await client.post(
        "/api/merchant/orders",
        json={
            "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
            "table_number": "A3",
        },
        headers=auth_headers(merchant_session),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["customer_id"] is None
    assert body["payment_method"] == "CASH", "商家建單預設為現金"
    assert body["table_number"] == "A3"


async def test_顧客只看得到自己的訂單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """篩選條件取自 token，不存在改 URL 就能看到別人訂單的可能。"""
    await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )

    other = await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "路人",
            "email": "stranger@test.com",
            "password": "password123",
        },
    )
    assert other.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"role": "customer", "email": "stranger@test.com", "password": "password123"},
    )

    response = await client.get("/api/orders", headers=auth_headers(login.json()))
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# 狀態機
# ---------------------------------------------------------------------------


async def test_合法的狀態轉移(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]
    headers = auth_headers(merchant_session)

    for target in ("ACCEPTED", "PREPARING", "READY", "COMPLETED"):
        response = await client.put(
            f"/api/orders/{order_id}/status", json={"status": target}, headers=headers
        )
        assert response.status_code == 200, f"{target}: {response.text}"
        assert response.json()["status"] == target


async def test_跳躍式狀態轉移會被拒絕(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """PENDING 只能轉到 ACCEPTED 或 REJECTED，不能直接跳到 COMPLETED。"""
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )

    response = await client.put(
        f"/api/orders/{order.json()['id']}/status",
        json={"status": "COMPLETED"},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 409


async def test_終止狀態無法再轉移(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]
    headers = auth_headers(merchant_session)

    await client.put(
        f"/api/orders/{order_id}/status",
        json={"status": "REJECTED", "reject_reason": "今日售完"},
        headers=headers,
    )

    response = await client.put(
        f"/api/orders/{order_id}/status", json={"status": "ACCEPTED"}, headers=headers
    )
    assert response.status_code == 409


async def test_拒絕訂單必須提供原因(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )

    response = await client.put(
        f"/api/orders/{order.json()['id']}/status",
        json={"status": "REJECTED"},
        headers=auth_headers(merchant_session),
    )
    assert response.status_code == 422


async def test_商家不能改別人的訂單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )

    await client.post(
        "/api/auth/register",
        json={
            "role": "merchant",
            "name": "別間店",
            "email": "shop-c@test.com",
            "password": "password123",
        },
    )
    login = await client.post(
        "/api/auth/login",
        json={"role": "merchant", "email": "shop-c@test.com", "password": "password123"},
    )

    response = await client.put(
        f"/api/orders/{order.json()['id']}/status",
        json={"status": "ACCEPTED"},
        headers=auth_headers(login.json()),
    )
    assert response.status_code == 403
