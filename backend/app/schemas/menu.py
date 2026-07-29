"""餐點與庫存的 schema。

對照舊版 `routes/menu.py`：建立與更新餐點合計約 40 行手寫驗證
（`try: price = float(price) except ...`、`if price <= 0`、`if stock < 0`…），
在這裡由型別註記與 Field 約束取代，且驗證規則會自動出現在 OpenAPI 文件上。
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Name = Annotated[str, Field(min_length=1, max_length=100)]
Price = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
Stock = Annotated[int, Field(ge=0)]


class MenuItemCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "招牌漢堡",
                "price": "120.00",
                "description": "手打牛肉排",
                "stock": 50,
            }
        }
    )

    name: Name
    price: Price
    description: Annotated[str | None, Field(default=None, max_length=500)]
    stock: Stock = 0


class MenuItemUpdate(BaseModel):
    """部分更新：所有欄位皆為選填，只更新有帶的欄位。

    舊版用 `if "name" in data:` 逐一判斷；這裡用
    `model_dump(exclude_unset=True)` 精確區分「沒帶這個欄位」與「帶了 null」。
    """

    name: Name | None = None
    price: Price | None = None
    description: Annotated[str | None, Field(default=None, max_length=500)]
    stock: Stock | None = None
    is_active: bool | None = None
    is_available: bool | None = None


class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    name: str
    price: Decimal
    description: str | None
    stock: int
    is_available: bool
    is_active: bool
