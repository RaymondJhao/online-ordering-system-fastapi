"""訂單的商業邏輯。

舊版 `routes/order.py` 有 505 行，單一函式同時處理 HTTP 解析、輸入驗證、
商業規則與資料存取，兩個建單端點（顧客／商家）各自複製了一份幾乎相同的流程。

這裡把驗證交給 Pydantic、把流程收斂成一個 `_create_order`，
兩個端點的差異只剩「訂單屬於誰」與「預設付款方式」。
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    IdempotencyRecord,
    MenuItem,
    Merchant,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
)
from app.schemas.order import OrderItemCreate, OrderItemResponse, OrderResponse
from app.services import coupon_service, stock_service

# 嚴格的狀態轉移表。key 是目前狀態，value 是允許轉入的狀態集合；
# 不在表中的轉移一律拒絕，包含「轉回自己」與跳躍式轉移。
#
# 用明確的轉移表而非一連串 if，好處是規則可以一眼讀完，也能直接當作
# 給前端或商家的文件。
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: {OrderStatus.REFUNDED},
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}

# 這些狀態代表訂單不會再出餐，佔用的庫存應該還給其他顧客
_STOCK_RELEASING_STATUSES = {
    OrderStatus.REJECTED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
}


class MerchantNotFoundError(Exception):
    pass


class InvalidMenuItemsError(Exception):
    pass


class OrderNotFoundError(Exception):
    pass


class NotOwnerError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class IdempotentReplay:
    """代表這次請求命中了先前已處理過的 Idempotency-Key。"""

    body: dict


def serialize_order(order: Order) -> OrderResponse:
    """把 ORM 物件轉為回應。

    呼叫前必須已經 eager load `order_items` 與其 `menu_item`，
    否則在 async 下存取 `item.menu_item.name` 會拋 MissingGreenlet。
    `get_order_detail()` 已處理好，不要繞過它直接查詢。
    """
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        merchant_id=order.merchant_id,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        reject_reason=order.reject_reason,
        total_price=order.total_price,
        coupon_id=order.coupon_id,
        discount_amount=order.discount_amount,
        pickup_time=order.pickup_time,
        table_number=order.table_number,
        created_at=order.created_at,
        items=[
            OrderItemResponse(
                menu_item_id=item.menu_item_id,
                name=item.menu_item.name,
                quantity=item.quantity,
                price=item.price,
            )
            for item in order.order_items
        ],
    )


def _eager_loaded():
    """訂單序列化需要的兩層關聯。"""
    return selectinload(Order.order_items).selectinload(OrderItem.menu_item)


async def get_order_detail(db: AsyncSession, order_id: int) -> Order | None:
    result = await db.execute(select(Order).where(Order.id == order_id).options(_eager_loaded()))
    return result.scalar_one_or_none()


async def list_orders(db: AsyncSession, *, role: str, user_id: int) -> list[Order]:
    column = Order.customer_id if role == "customer" else Order.merchant_id
    result = await db.execute(
        select(Order)
        .where(column == user_id)
        .options(_eager_loaded())
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


async def _load_menu_items(
    db: AsyncSession, *, items: list[OrderItemCreate], merchant_id: int
) -> dict[int, MenuItem]:
    """撈出訂單內所有餐點，並確認它們都屬於指定商家。

    一次查完而不是逐筆 get()，除了效率，也是為了讓「有品項不屬於這個商家」
    這種情況在下單前就被擋下，而不是扣了一半庫存才發現。
    """
    menu_item_ids = {item.menu_item_id for item in items}
    result = await db.execute(
        select(MenuItem).where(MenuItem.id.in_(menu_item_ids), MenuItem.merchant_id == merchant_id)
    )
    menu_item_map = {menu_item.id: menu_item for menu_item in result.scalars().all()}

    if len(menu_item_map) != len(menu_item_ids):
        raise InvalidMenuItemsError("部分餐點不存在，或不屬於指定的商家")

    return menu_item_map


async def _create_order(
    db: AsyncSession,
    *,
    customer_id: int | None,
    merchant_id: int,
    items: list[OrderItemCreate],
    payment_method: PaymentMethod,
    pickup_time,
    table_number: str | None,
    coupon_code: str | None,
    idempotency_key: str | None = None,
) -> Order:
    """建立訂單。顧客下單與商家建單共用這一份流程。

    交易邊界：訂單、所有明細、庫存扣減與冪等紀錄全部寫在同一筆交易，
    任何一步失敗都整筆 rollback，不會出現「庫存扣了但訂單沒建立」。
    """
    coupon = await coupon_service.resolve_coupon(db, code=coupon_code, merchant_id=merchant_id)
    menu_item_map = await _load_menu_items(db, items=items, merchant_id=merchant_id)

    try:
        order = Order(
            customer_id=customer_id,
            merchant_id=merchant_id,
            total_price=Decimal(0),
            status=OrderStatus.PENDING,
            payment_method=payment_method,
            table_number=table_number,
            pickup_time=pickup_time,
        )

        # 單價一律取自資料庫，不接受前端傳來的金額
        total_price = Decimal(0)
        for item in items:
            menu_item = menu_item_map[item.menu_item_id]
            total_price += menu_item.price * item.quantity
            order.order_items.append(
                OrderItem(
                    menu_item_id=menu_item.id,
                    quantity=item.quantity,
                    price=menu_item.price,
                )
            )

        discount_amount = coupon_service.calculate_discount(total_price, coupon)
        order.discount_amount = discount_amount
        order.total_price = total_price - discount_amount
        if coupon is not None:
            order.coupon_id = coupon.id

        await stock_service.deduct_stock(db, [(item.menu_item_id, item.quantity) for item in items])

        db.add(order)
        await db.flush()  # 取得 order.id

        if idempotency_key:
            db.add(IdempotencyRecord(key=idempotency_key, response_body={"order_id": order.id}))

        await db.commit()
    except Exception:
        # 庫存扣減已經發生在這筆交易裡，必須確實 rollback
        await db.rollback()
        raise

    return order


async def create_customer_order(
    db: AsyncSession,
    *,
    customer_id: int,
    merchant_id: int,
    items: list[OrderItemCreate],
    payment_method: PaymentMethod,
    pickup_time,
    table_number: str | None,
    coupon_code: str | None,
    idempotency_key: str | None,
) -> Order | IdempotentReplay:
    """顧客下單，支援 Idempotency-Key。

    客戶端在網路逾時重試、或使用者連點兩次送出時，可能用同一把 key 送出
    兩筆相同請求。第一次處理完會把 key 與訂單 id 一起寫入資料庫，
    第二次直接回放結果，不重複扣庫存也不重複建單。
    """
    if idempotency_key:
        replay = await _find_idempotent_result(db, idempotency_key)
        if replay is not None:
            return replay

    if await db.get(Merchant, merchant_id) is None:
        raise MerchantNotFoundError("商家不存在")

    try:
        return await _create_order(
            db,
            customer_id=customer_id,
            merchant_id=merchant_id,
            items=items,
            payment_method=payment_method,
            pickup_time=pickup_time,
            table_number=table_number,
            coupon_code=coupon_code,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        # 極端併發：兩個帶著相同 key 的請求同時通過了上面的「查無紀錄」檢查。
        # unique 約束會讓後 commit 的那個在這裡失敗，它自己的庫存扣減已隨
        # rollback 撤銷，改回放先寫入成功那筆的結果。
        if idempotency_key:
            replay = await _find_idempotent_result(db, idempotency_key)
            if replay is not None:
                return replay
        raise


async def _find_idempotent_result(
    db: AsyncSession, idempotency_key: str
) -> IdempotentReplay | None:
    result = await db.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.key == idempotency_key)
    )
    record = result.scalar_one_or_none()
    return IdempotentReplay(body=record.response_body) if record else None


async def create_merchant_order(
    db: AsyncSession,
    *,
    merchant_id: int,
    items: list[OrderItemCreate],
    payment_method: PaymentMethod,
    pickup_time,
    table_number: str | None,
    coupon_code: str | None,
) -> Order:
    """商家在店內或電話建立的訂單：沒有顧客帳號，customer_id 為 null。"""
    return await _create_order(
        db,
        customer_id=None,
        merchant_id=merchant_id,
        items=items,
        payment_method=payment_method,
        pickup_time=pickup_time,
        table_number=table_number,
        coupon_code=coupon_code,
    )


async def update_status(
    db: AsyncSession,
    *,
    merchant_id: int,
    order_id: int,
    new_status: OrderStatus,
    reject_reason: str | None,
) -> Order:
    """更新訂單狀態，並在訂單終止時把庫存還回去。

    庫存回補是舊版沒有的行為：舊版拒絕或取消訂單時只改狀態，
    已扣掉的庫存不會回來，等於商家每拒絕一筆訂單就永久少掉那些庫存。
    """
    order = await get_order_detail(db, order_id)

    if order is None:
        raise OrderNotFoundError("訂單不存在")
    if order.merchant_id != merchant_id:
        raise NotOwnerError("無權操作此訂單")

    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        raise InvalidStatusTransitionError(
            f"無法將訂單狀態從 {order.status.value} 轉換為 {new_status.value}"
        )

    if new_status is OrderStatus.REJECTED and reject_reason:
        order.reject_reason = reject_reason.strip()

    if new_status in _STOCK_RELEASING_STATUSES:
        await stock_service.restore_stock(
            db, [(item.menu_item_id, item.quantity) for item in order.order_items]
        )

    order.status = new_status
    await db.commit()
    return order
