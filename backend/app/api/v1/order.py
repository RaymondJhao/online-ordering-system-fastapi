"""訂單端點。

對照舊版：`create_order` 一個函式 180 行（含 60 行 YAML docstring 與
十餘個驗證分支）。這裡的路由函式只做三件事——呼叫 service、把領域例外
轉成 HTTP 狀態碼、回傳序列化結果。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import DbSession, TokenPayloadDep, require_role
from app.core.security import TokenPayload
from app.schemas.order import (
    CustomerOrderCreate,
    MerchantOrderCreate,
    OrderResponse,
    OrderStatusUpdate,
)
from app.services import order_service
from app.services.coupon_service import CouponNotApplicableError
from app.services.order_service import (
    IdempotentReplay,
    InvalidMenuItemsError,
    InvalidStatusTransitionError,
    MerchantNotFoundError,
    NotOwnerError,
    OrderNotFoundError,
)
from app.services.stock_service import InsufficientStockError

router = APIRouter(prefix="/orders", tags=["Order"])
merchant_router = APIRouter(prefix="/merchant", tags=["Merchant Order"])

CustomerOnly = Annotated[TokenPayload, Depends(require_role("customer"))]
MerchantOnly = Annotated[TokenPayload, Depends(require_role("merchant"))]

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description="帶上同一把 key 重送時不會重複建單，適用於網路逾時重試或重複點擊",
    ),
]


async def _load_response(db: DbSession, order_id: int) -> OrderResponse:
    """重新查詢並 eager load 關聯後再序列化。

    建單流程中的 order 物件沒有載入 order_items.menu_item，
    直接序列化會在 async 下拋 MissingGreenlet。
    """
    order = await order_service.get_order_detail(db, order_id)
    if order is None:  # pragma: no cover - 剛建立完必定存在
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="訂單不存在")
    return order_service.serialize_order(order)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="顧客下單",
)
async def create_order(
    payload: CustomerOrderCreate,
    db: DbSession,
    token: CustomerOnly,
    idempotency_key: IdempotencyKey = None,
) -> OrderResponse:
    """建立訂單。

    總價由後端依資料庫單價計算，請求中不接受任何金額欄位。
    庫存扣減與訂單寫入在同一筆交易內完成，庫存不足時整筆失敗。
    """
    try:
        result = await order_service.create_customer_order(
            db,
            customer_id=token.subject,
            merchant_id=payload.merchant_id,
            items=payload.items,
            payment_method=payload.payment_method,
            pickup_time=payload.pickup_time,
            table_number=payload.table_number,
            coupon_code=payload.coupon_code,
            idempotency_key=idempotency_key,
        )
    except MerchantNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InvalidMenuItemsError, CouponNotApplicableError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        # 409 而非 400：請求本身是合法的，只是與目前的庫存狀態衝突
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if isinstance(result, IdempotentReplay):
        return await _load_response(db, result.body["order_id"])

    return await _load_response(db, result.id)


@merchant_router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="商家建立現場／電話訂單",
)
async def create_merchant_order(
    payload: MerchantOrderCreate, db: DbSession, token: MerchantOnly
) -> OrderResponse:
    """商家自行建立的訂單沒有對應的顧客帳號，customer_id 為 null。

    商家身分取自 token，前端無法指定 merchant_id。
    """
    try:
        order = await order_service.create_merchant_order(
            db,
            merchant_id=token.subject,
            items=payload.items,
            payment_method=payload.payment_method,
            pickup_time=payload.pickup_time,
            table_number=payload.table_number,
            coupon_code=payload.coupon_code,
        )
    except (InvalidMenuItemsError, CouponNotApplicableError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return await _load_response(db, order.id)


@router.get("", response_model=list[OrderResponse], summary="查詢訂單")
async def list_orders(db: DbSession, token: TokenPayloadDep) -> list[OrderResponse]:
    """顧客看到自己的訂單，商家看到自己店裡的訂單。

    篩選條件取自 token 而非查詢參數，因此不存在「改一下 URL 就能看到
    別人訂單」的可能。
    """
    orders = await order_service.list_orders(db, role=token.role, user_id=token.subject)
    return [order_service.serialize_order(order) for order in orders]


@router.put("/{order_id}/status", response_model=OrderResponse, summary="更新訂單狀態")
async def update_order_status(
    order_id: int, payload: OrderStatusUpdate, db: DbSession, token: MerchantOnly
) -> OrderResponse:
    """依狀態機規則更新訂單狀態。

    轉移規則見 `order_service.ALLOWED_TRANSITIONS`。訂單被拒絕、取消或
    退款時，佔用的庫存會自動釋放回去。
    """
    try:
        order = await order_service.update_status(
            db,
            merchant_id=token.subject,
            order_id=order_id,
            new_status=payload.status,
            reject_reason=payload.reject_reason,
        )
    except OrderNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotOwnerError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return order_service.serialize_order(order)
