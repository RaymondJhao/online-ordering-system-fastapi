"""定期維護工作。

**自動釋出未付款訂單佔用的庫存**

顧客下單後訂單狀態是 PENDING、付款狀態是 UNPAID，此時庫存已經扣掉了——
商家知道要準備哪些餐點，這些餐點也不該再賣給別人。但如果顧客遲遲不去完成
付款，這筆訂單等於無限期佔用庫存，其他顧客明明看得到菜單卻買不到。

因此需要一個排程定期把逾時未付款的訂單視為棄單、自動取消，並把庫存還回去。

**與舊版的差異**

舊版 `tasks.py` 的 docstring 寫著「自動轉成 CANCELLED，把庫存釋放回去」，
但實際程式碼只有 `order.status = OrderStatus.CANCELLED`，沒有任何回補庫存的
動作。也就是說這個排程每跑一次，被取消訂單佔用的庫存就永久消失一次——
它宣稱要解決的問題，恰恰是它自己造成的。這裡補上實際的回補邏輯。
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import Order, OrderItem, OrderStatus, PaymentStatus
from app.services import stock_service

logger = logging.getLogger(__name__)


async def cancel_expired_unpaid_orders(db: AsyncSession) -> list[int]:
    """取消逾時未付款的訂單並回補庫存，回傳被取消的訂單 id。

    只挑「尚未付款」且「商家尚未處理」、且建立時間早於門檻的訂單；
    已在處理中、已完成、已取消的訂單都不受影響。
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.UNPAID_ORDER_TIMEOUT_MINUTES)

    result = await db.execute(
        select(Order)
        .where(
            Order.status == OrderStatus.PENDING,
            Order.payment_status == PaymentStatus.UNPAID,
            Order.created_at < cutoff,
        )
        # 回補庫存需要明細，必須 eager load，否則在 async 下會拋 MissingGreenlet
        .options(selectinload(Order.order_items).selectinload(OrderItem.menu_item))
    )
    expired_orders = list(result.scalars().all())

    if not expired_orders:
        return []

    try:
        for order in expired_orders:
            await stock_service.restore_stock(
                db, [(item.menu_item_id, item.quantity) for item in order.order_items]
            )
            order.status = OrderStatus.CANCELLED

        await db.commit()
    except Exception:
        # 任何一步出錯都整批 rollback，避免訂單狀態改到一半、庫存回補到一半
        await db.rollback()
        logger.exception("自動取消逾時未付款訂單時發生錯誤，已 rollback")
        raise

    order_ids = [order.id for order in expired_orders]
    logger.info("已自動取消 %d 筆逾時未付款訂單並釋出庫存：%s", len(order_ids), order_ids)
    return order_ids
