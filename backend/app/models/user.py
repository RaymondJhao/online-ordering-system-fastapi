"""顧客與商家。

與舊版的差異：model 上不再有 `set_password()` / `check_password()`。

密碼雜湊屬於安全性關注點，放在 model 會讓 ORM 同時承擔「資料結構」與
「密碼學操作」兩種責任；更實際的問題是 bcrypt 是 CPU 密集運算，在 async
環境必須丟到 threadpool 執行，把它藏在 model 的方法裡很容易被誤用在
event loop 上。Phase 2 會統一放到 `app/core/security.py`。
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.coupon import Coupon
    from app.models.menu import MenuItem
    from app.models.order import Order


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    orders: Mapped[list["Order"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="merchant",
        cascade="all, delete-orphan",
    )
    orders: Mapped[list["Order"]] = relationship(
        back_populates="merchant",
        cascade="all, delete-orphan",
    )
    coupons: Mapped[list["Coupon"]] = relationship(
        back_populates="merchant",
        cascade="all, delete-orphan",
    )
