"""優惠券 schema。"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import DiscountType


class CouponCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "OPEN888",
                "discount_type": "FIXED",
                "discount_value": 50,
                "is_active": True,
            }
        }
    )

    code: Annotated[str, Field(min_length=1, max_length=50)]
    discount_type: DiscountType
    discount_value: Annotated[int, Field(gt=0)]
    is_active: bool = True

    @model_validator(mode="after")
    def _check_percentage_range(self) -> Self:
        """百分比折扣不可超過 100。

        這是跨欄位的規則（discount_value 的合法範圍取決於 discount_type），
        單一欄位的 Field 約束表達不了，因此用 model_validator。
        """
        if self.discount_type is DiscountType.PERCENTAGE and self.discount_value > 100:
            raise ValueError("discount_type 為 PERCENTAGE 時，discount_value 不可超過 100")
        return self


class CouponResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    discount_type: DiscountType
    discount_value: int
    is_active: bool
    merchant_id: int
