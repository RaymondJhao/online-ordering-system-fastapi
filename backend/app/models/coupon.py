"""優惠券。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import DiscountType, pg_enum

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import Merchant


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (CheckConstraint("discount_value > 0", name="discount_value_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    discount_type: Mapped[DiscountType] = mapped_column(pg_enum(DiscountType, "discount_type"))
    discount_value: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    merchant: Mapped["Merchant"] = relationship(back_populates="coupons")
    orders: Mapped[list["Order"]] = relationship(back_populates="coupon")
