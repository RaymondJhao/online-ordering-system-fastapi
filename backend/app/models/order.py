"""訂單與訂單明細。"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus, pg_enum

if TYPE_CHECKING:
    from app.models.coupon import Coupon
    from app.models.menu import MenuItem
    from app.models.user import Customer, Merchant


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # 背景排程每分鐘執行一次「找出逾時未付款訂單」的查詢，條件是
        # status + payment_status + created_at。沒有這個複合索引時，
        # 訂單量成長後每分鐘都會做一次全表掃描。
        Index(
            "ix_orders_pending_unpaid",
            "status",
            "payment_status",
            "created_at",
        ),
        Index("ix_orders_merchant_created", "merchant_id", "created_at"),
        CheckConstraint("total_price >= 0", name="total_price_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 商家在店內或電話建立的訂單沒有對應的顧客帳號，因此允許為空
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"))
    total_price: Mapped[Decimal]
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("coupons.id", ondelete="SET NULL"))
    discount_amount: Mapped[int] = mapped_column(default=0)
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"), default=OrderStatus.PENDING
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, "payment_status"), default=PaymentStatus.UNPAID
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        pg_enum(PaymentMethod, "payment_method"), default=PaymentMethod.ONLINE
    )
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    pickup_time: Mapped[datetime | None]
    table_number: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    customer: Mapped["Customer | None"] = relationship(back_populates="orders")
    merchant: Mapped["Merchant"] = relationship(back_populates="orders")
    coupon: Mapped["Coupon | None"] = relationship(back_populates="orders")
    order_items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    """Order 與 MenuItem 之間的關聯物件，額外攜帶數量與成交單價。

    `price` 記錄的是「下單當下」的單價，不能改成查 MenuItem.price——
    商家日後調價時，歷史訂單的金額必須維持不變。
    """

    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(default=1)
    price: Mapped[Decimal]

    order: Mapped["Order"] = relationship(back_populates="order_items")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="order_items")
