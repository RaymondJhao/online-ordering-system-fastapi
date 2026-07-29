"""金流端點與綠界回調驗證。"""

from httpx import AsyncClient

from app.utils.ecpay import generate_check_mac_value
from tests.conftest import auth_headers


async def _place_order(client, customer_session, merchant_id, item_id, **extra):
    return await client.post(
        "/api/orders",
        json={
            "merchant_id": merchant_id,
            "items": [{"menu_item_id": item_id, "quantity": 1}],
            **extra,
        },
        headers=auth_headers(customer_session),
    )


async def test_建立付款回傳綠界表單參數(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]

    response = await client.post(
        f"/api/payment/checkout/{order_id}", headers=auth_headers(customer_session)
    )

    assert response.status_code == 200
    body = response.json()
    assert "payment-stage.ecpay.com.tw" in body["payment_url"]

    form = body["form_data"]
    assert form["CheckMacValue"]
    assert form["TotalAmount"] == 120
    assert form["CustomField1"] == str(order_id), "用 CustomField 帶回 order_id，不從交易編號反推"


async def test_不能替別人的訂單建立付款(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )

    await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "路人",
            "email": "intruder@test.com",
            "password": "password123",
        },
    )
    login = await client.post(
        "/api/auth/login",
        json={"role": "customer", "email": "intruder@test.com", "password": "password123"},
    )

    response = await client.post(
        f"/api/payment/checkout/{order.json()['id']}", headers=auth_headers(login.json())
    )
    assert response.status_code == 403


async def test_現金訂單不能建立線上付款(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client,
        customer_session,
        merchant_session["user"]["id"],
        merchant_menu_item["id"],
        payment_method="CASH",
    )

    response = await client.post(
        f"/api/payment/checkout/{order.json()['id']}", headers=auth_headers(customer_session)
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 綠界回調
# ---------------------------------------------------------------------------


def _signed_callback(order_id: int, rtn_code: str = "1") -> dict[str, str]:
    data = {
        "MerchantID": "2000132",
        "MerchantTradeNo": f"ORD{order_id}999",
        "RtnCode": rtn_code,
        "RtnMsg": "Succeeded" if rtn_code == "1" else "Failed",
        "TradeAmt": "120",
        "CustomField1": str(order_id),
    }
    data["CheckMacValue"] = generate_check_mac_value(data)
    return data


async def test_合法回調會把訂單標記為已付款(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]

    response = await client.post("/api/payment/callback", data=_signed_callback(order_id))

    assert response.status_code == 200
    assert response.text == "1|OK", "回應必須是純文字，回 JSON 會讓綠界持續重送"

    orders = await client.get("/api/orders", headers=auth_headers(customer_session))
    updated = next(o for o in orders.json() if o["id"] == order_id)
    assert updated["payment_status"] == "PAID"


async def test_竄改過的回調會被拒絕(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """這個端點沒有登入者，身分完全靠 CheckMacValue 確認。

    少了這道驗證，任何人都能自行 POST 一筆「付款成功」把訂單改成已付款——
    等於免費點餐。
    """
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]

    tampered = _signed_callback(order_id)
    tampered["TradeAmt"] = "1"  # 簽章是對原本的內容算的，改了金額就對不上

    response = await client.post("/api/payment/callback", data=tampered)

    assert response.text == "0|Error"

    orders = await client.get("/api/orders", headers=auth_headers(customer_session))
    assert next(o for o in orders.json() if o["id"] == order_id)["payment_status"] == "UNPAID"


async def test_沒有簽章的回調會被拒絕(client: AsyncClient) -> None:
    response = await client.post(
        "/api/payment/callback", data={"RtnCode": "1", "CustomField1": "1"}
    )
    assert response.text == "0|Error"


async def test_付款失敗的通知不會改動訂單(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """RtnCode 不是 1 代表付款失敗，但仍要回 1|OK，否則綠界會持續重送。"""
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]

    response = await client.post(
        "/api/payment/callback", data=_signed_callback(order_id, rtn_code="0")
    )

    assert response.text == "1|OK"
    orders = await client.get("/api/orders", headers=auth_headers(customer_session))
    assert next(o for o in orders.json() if o["id"] == order_id)["payment_status"] == "UNPAID"


async def test_重複送達的回調具冪等性(
    client: AsyncClient, customer_session: dict, merchant_session: dict, merchant_menu_item: dict
) -> None:
    """綠界可能重送同一筆通知，重複處理不可出錯。"""
    order = await _place_order(
        client, customer_session, merchant_session["user"]["id"], merchant_menu_item["id"]
    )
    order_id = order.json()["id"]
    payload = _signed_callback(order_id)

    first = await client.post("/api/payment/callback", data=payload)
    second = await client.post("/api/payment/callback", data=payload)

    assert first.text == second.text == "1|OK"


def test_CheckMacValue_對內容變動敏感() -> None:
    """簽章必須隨任何欄位變動而改變，否則就攔不住竄改。"""
    base = {"MerchantID": "2000132", "RtnCode": "1", "TradeAmt": "120"}
    changed = {**base, "TradeAmt": "1"}

    assert generate_check_mac_value(base) != generate_check_mac_value(changed)
    assert generate_check_mac_value(base) == generate_check_mac_value(dict(base))
