"""綠界金流串接。"""

import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.utils.ecpay import generate_check_mac_value

ECPAY_CHECKOUT_URL = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"

logger = logging.getLogger(__name__)


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

    # ClientBackURL 只在有設定時才送。空字串會被綠界視為無效參數，
    # 而且它會參與 CheckMacValue 的計算，不能用空值佔位。
    if settings.ECPAY_CLIENT_BACK_URL:
        params["ClientBackURL"] = settings.ECPAY_CLIENT_BACK_URL

    params["CheckMacValue"] = generate_check_mac_value(params)
    return params


def _redacted_for_log(data: dict[str, str]) -> list[tuple[str, str]]:
    """把回調內容整理成可寫進日誌的形式，並遮蔽卡號相關欄位。

    簽章不符時，只知道欄位「名稱」是不夠的——問題幾乎都出在某個欄位的**值**
    含有編碼行為不一致的字元。要定位就必須看得到實際內容。

    綠界的信用卡通知會帶 card4no／card6no（卡號的前六後四）。那是持卡人資料，
    不該進日誌，因此一律遮蔽。其餘欄位都是交易中介資料，記錄無妨。
    """
    return [
        (key, "<redacted>" if "card" in key.lower() else value)
        for key, value in sorted(data.items())
    ]


async def handle_callback(db: AsyncSession, form_data: dict[str, str]) -> bool:
    """處理綠界的付款結果通知，回傳是否成功受理。

    這個端點由綠界的伺服器直接呼叫，沒有登入者，因此不能用 JWT 驗證身分。
    改以 CheckMacValue 確認這筆通知確實來自綠界且內容未被竄改——
    少了這道驗證，任何人都可以自行 POST 一筆「付款成功」把訂單改成已付款。
    """
    data = dict(form_data)
    received_mac = data.pop("CheckMacValue", None)

    # 這裡的每一條 return 都必須留下紀錄。這個端點的所有失敗路徑都回 HTTP 200
    # （綠界只看回應內容是 1|OK 還是 0|Error），而其中三條會回 1|OK 卻不更新
    # 任何資料——綠界因此認定通知成功、不再重送，付款狀態卻永遠停在 UNPAID。
    # 沒有日誌的話，這個組合從外部完全無法區分「通知沒送到」與「送到了但被丟棄」。
    logger.info(
        "收到綠界回調：MerchantTradeNo=%s RtnCode=%s CustomField1=%s",
        data.get("MerchantTradeNo"),
        data.get("RtnCode"),
        data.get("CustomField1"),
    )

    if not received_mac:
        logger.warning("綠界回調缺少 CheckMacValue，已拒絕")
        return False

    expected_mac = generate_check_mac_value(data)
    if received_mac != expected_mac:
        # 刻意記下兩個雜湊值。簽章不符的原因幾乎都是參數集合或編碼細節有落差，
        # 而不是遭到竄改；沒有實際數值可比對，這種問題無從下手。
        # 金鑰本身不會出現在日誌裡，雜湊值不足以反推。
        logger.warning(
            "綠界回調簽章不符：received=%s expected=%s 參與計算的內容=%s",
            received_mac,
            expected_mac,
            _redacted_for_log(data),
        )
        return False

    if data.get("RtnCode") != "1":
        # 付款失敗的通知也要回 1|OK，否則綠界會持續重送
        logger.info(
            "綠界回報付款未成功：RtnCode=%s RtnMsg=%s", data.get("RtnCode"), data.get("RtnMsg")
        )
        return True

    raw_order_id = data.get("CustomField1")
    if not raw_order_id or not raw_order_id.isdigit():
        logger.error("綠界回調的 CustomField1 無法解析為訂單編號：%r", raw_order_id)
        return True

    order = await db.get(Order, int(raw_order_id))

    if order is None:
        logger.error("綠界回調指向不存在的訂單：id=%s", raw_order_id)
        return True

    # 綠界可能重送同一筆通知，因此只在仍是 UNPAID 時更新，天然具備冪等性
    if order.payment_status is not PaymentStatus.UNPAID:
        logger.info("訂單 %s 的付款狀態已是 %s，略過（綠界重送）", order.id, order.payment_status)
        return True

    try:
        order.payment_status = PaymentStatus.PAID
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("更新訂單 %s 付款狀態時失敗，已 rollback", order.id)
        return False

    logger.info("訂單 %s 已標記為已付款", order.id)
    return True
