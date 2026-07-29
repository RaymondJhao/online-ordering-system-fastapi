"""餐點品項。"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.order import OrderItem
    from app.models.user import Merchant


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        # 原子扣庫存的 SQL 是 `UPDATE ... WHERE id = :id AND stock >= :qty`，
        # 靠 WHERE 條件擋住超賣。這條 CHECK 是第二道防線：即使日後有人寫了
        # 沒經過該路徑的更新，資料庫仍會拒絕把庫存扣成負數。
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal]
    description: Mapped[str | None] = mapped_column(String(500))
    is_available: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    stock: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    merchant: Mapped["Merchant"] = relationship(back_populates="menu_items")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="menu_item")
