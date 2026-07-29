"""訂單 schema。

舊版 `routes/order.py` 用四個 helper（`_parse_items`、`_parse_pickup_time` 等）
處理輸入驗證，每個都回傳 `(值, error_response)` 的二元組，呼叫端必須逐一
`if error_response: return error_response`。這裡全部由 Pydantic 取代，
路由函式因此不再有任何驗證分支。
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import OrderStatus, PaymentMethod, PaymentStatus


class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: Annotated[int, Field(gt=0)]


class _OrderCreateBase(BaseModel):
    items: Annotated[list[OrderItemCreate], Field(min_length=1)]
    pickup_time: datetime | None = None
    coupon_code: Annotated[str | None, Field(default=None, max_length=50)]
    table_number: Annotated[str | None, Field(default=None, max_length=20)]

    @field_validator("pickup_time")
    @classmethod
    def _validate_pickup_time(cls, value: datetime | None) -> datetime | None:
        """取餐時間必須是未來時間。

        資料庫欄位是 TIMESTAMP WITH TIME ZONE，因此沒帶時區的輸入一律視為 UTC
        後再比較。舊版是用 `datetime.now(tz)` 或 `datetime.now()` 依輸入切換
        比較基準，naive 輸入會被當成伺服器本地時間，跨時區時判斷會出錯。
        """
        if value is None:
            return None

        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if normalized <= datetime.now(UTC):
            raise ValueError("pickup_time 不可為過去時間")
        return normalized


class CustomerOrderCreate(_OrderCreateBase):
    """顧客下單。

    刻意「不」接受 total_price 或任何金額欄位——總價一律由後端依資料庫的
    單價重新計算，避免前端傳假價格。
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "merchant_id": 1,
                "items": [{"menu_item_id": 1, "quantity": 2}],
                "payment_method": "ONLINE",
                "coupon_code": "OPEN888",
            }
        }
    )

    merchant_id: int
    payment_method: PaymentMethod = PaymentMethod.ONLINE


class MerchantOrderCreate(_OrderCreateBase):
    """商家在店內或電話建立的訂單。

    沒有 merchant_id 欄位：商家身分直接取自 token，不可（也不該）由前端指定。
    預設付款方式為現金。
    """

    payment_method: PaymentMethod = PaymentMethod.CASH


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    reject_reason: Annotated[str | None, Field(default=None, max_length=255)]

    @model_validator(mode="after")
    def _require_reject_reason(self) -> Self:
        if self.status is OrderStatus.REJECTED and not (self.reject_reason or "").strip():
            raise ValueError("拒絕訂單時必須提供 reject_reason")
        return self


class OrderItemResponse(BaseModel):
    menu_item_id: int
    name: str
    quantity: int
    price: Decimal


class OrderResponse(BaseModel):
    id: int
    customer_id: int | None
    merchant_id: int
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    reject_reason: str | None
    total_price: Decimal
    coupon_id: int | None
    discount_amount: int
    pickup_time: datetime | None
    table_number: str | None
    created_at: datetime
    items: list[OrderItemResponse]
