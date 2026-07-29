"""綠界金流串接。"""

import time
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.utils.ecpay import generate_check_mac_value

ECPAY_CHECKOUT_URL = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"


class OrderNotFoundError(Exception):
    pass


class NotOwnerError(Exception):
    pass


class OrderNotPayableError(Exception):
    """訂單目前的狀態不允許建立付款。"""


async def build_checkout_params(
    db: AsyncSession, *, customer_id: int, order_id: int
) -> dict[str, Any]:
    order = await db.get(Order, order_id)

    if order is None:
        raise OrderNotFoundError("訂單不存在")
    if order.customer_id != customer_id:
        raise NotOwnerError("無權操作此訂單")
    if order.status is not OrderStatus.PENDING:
        raise OrderNotPayableError("此訂單目前狀態無法建立付款")
    if order.payment_status is not PaymentStatus.UNPAID:
        raise OrderNotPayableError("此訂單已完成付款或退款，無法重複建立付款")
    if order.payment_method is not PaymentMethod.ONLINE:
        raise OrderNotPayableError("此訂單為現金付款，無法建立線上刷卡")

    settings = get_settings()
    params: dict[str, Any] = {
        "MerchantID": settings.ECPAY_MERCHANT_ID,
        "MerchantTradeNo": f"ORD{order.id}{int(time.time())}",
        "MerchantTradeDate": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio",
        # 綠界的 TotalAmount 只接受整數（新台幣無小數）
        "TotalAmount": round(float(order.total_price)),
        "TradeDesc": "線上點餐訂單",
        "ItemName": "線上餐點",
        "ReturnURL": settings.ECPAY_RETURN_URL,
        "ChoosePayment": "Credit",
        "EncryptType": 1,
        # 綠界會原封不動把 CustomField1~4 回傳到 ReturnURL，用它帶回 order_id。
        # 不要從 MerchantTradeNo 反推——id 與 timestamp 之間沒有分隔符，解析會有歧義。
        "CustomField1": str(order.id),
    }
    params["CheckMacValue"] = generate_check_mac_value(params)
    return params


async def handle_callback(db: AsyncSession, form_data: dict[str, str]) -> bool:
    """處理綠界的付款結果通知，回傳是否成功受理。

    這個端點由綠界的伺服器直接呼叫，沒有登入者，因此不能用 JWT 驗證身分。
    改以 CheckMacValue 確認這筆通知確實來自綠界且內容未被竄改——
    少了這道驗證，任何人都可以自行 POST 一筆「付款成功」把訂單改成已付款。
    """
    data = dict(form_data)
    received_mac = data.pop("CheckMacValue", None)

    if not received_mac or received_mac != generate_check_mac_value(data):
        return False

    if data.get("RtnCode") != "1":
        # 付款失敗的通知也要回 1|OK，否則綠界會持續重送
        return True

    raw_order_id = data.get("CustomField1")
    if not raw_order_id or not raw_order_id.isdigit():
        return True

    order = await db.get(Order, int(raw_order_id))

    # 綠界可能重送同一筆通知，因此只在仍是 UNPAID 時更新，天然具備冪等性
    if order is not None and order.payment_status is PaymentStatus.UNPAID:
        try:
            order.payment_status = PaymentStatus.PAID
            await db.commit()
        except Exception:
            await db.rollback()
            return False

    return True
