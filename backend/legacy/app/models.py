import enum
from datetime import datetime, timezone

from sqlalchemy.ext.associationproxy import association_proxy

from .extensions import bcrypt, db


def utcnow():
    return datetime.now(timezone.utc)


class OrderStatus(enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentStatus(enum.Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentMethod(enum.Enum):
    CASH = "CASH"
    ONLINE = "ONLINE"


class DiscountType(enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # one customer -> many orders
    orders = db.relationship(
        "Order", back_populates="customer", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


class Merchant(db.Model):
    __tablename__ = "merchants"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(255))
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # one merchant -> many menu items / orders
    menu_items = db.relationship(
        "MenuItem", back_populates="merchant", cascade="all, delete-orphan"
    )
    orders = db.relationship(
        "Order", back_populates="merchant", cascade="all, delete-orphan"
    )
    coupons = db.relationship(
        "Coupon", back_populates="merchant", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    merchant_id = db.Column(
        db.Integer, db.ForeignKey("merchants.id"), nullable=False
    )
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(500))
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    merchant = db.relationship("Merchant", back_populates="menu_items")
    # one menu item -> many order lines
    order_items = db.relationship("OrderItem", back_populates="menu_item")

    # many-to-many view: every Order this item has appeared in
    orders = association_proxy("order_items", "order")


class Coupon(db.Model):
    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(
        db.Enum(DiscountType, values_callable=lambda e: [member.value for member in e]),
        nullable=False,
    )
    discount_value = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    merchant_id = db.Column(
        db.Integer, db.ForeignKey("merchants.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    merchant = db.relationship("Merchant", back_populates="coupons")
    orders = db.relationship("Order", back_populates="coupon")


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    # 商家在大螢幕手動建立的現場／電話訂單沒有對應的顧客帳號，因此允許為空
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.id"), nullable=True
    )
    merchant_id = db.Column(
        db.Integer, db.ForeignKey("merchants.id"), nullable=False
    )
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    coupon_id = db.Column(
        db.Integer, db.ForeignKey("coupons.id"), nullable=True
    )
    discount_amount = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(
        db.Enum(OrderStatus, values_callable=lambda e: [member.value for member in e]),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    payment_status = db.Column(
        db.Enum(PaymentStatus, values_callable=lambda e: [member.value for member in e]),
        default=PaymentStatus.UNPAID,
        nullable=False,
    )
    payment_method = db.Column(
        db.Enum(PaymentMethod, values_callable=lambda e: [member.value for member in e]),
        default=PaymentMethod.ONLINE,
        nullable=False,
    )
    reject_reason = db.Column(db.String(255), nullable=True)
    pickup_time = db.Column(db.DateTime)
    table_number = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    customer = db.relationship("Customer", back_populates="orders")
    merchant = db.relationship("Merchant", back_populates="orders")
    coupon = db.relationship("Coupon", back_populates="orders")
    # one order -> many order lines
    order_items = db.relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )

    # many-to-many view: every MenuItem included in this order
    menu_items = association_proxy("order_items", "menu_item")


class OrderItem(db.Model):
    """Association object between Order and MenuItem (many-to-many),
    carrying the extra quantity/price columns for each order line."""

    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    menu_item_id = db.Column(
        db.Integer, db.ForeignKey("menu_items.id"), nullable=False
    )
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Numeric(10, 2), nullable=False)

    order = db.relationship("Order", back_populates="order_items")
    menu_item = db.relationship("MenuItem", back_populates="order_items")


class TokenBlocklist(db.Model):
    """已登出／被撤銷的 JWT，記錄其 jti 供 token_in_blocklist_loader 查詢比對。"""

    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class IdempotencyRecord(db.Model):
    """記錄已處理過的 Idempotency-Key 與其對應的回應內容，
    用來防止客戶端重試/雙擊送出同一筆請求時重複扣庫存、重複建單。"""

    __tablename__ = "idempotency_records"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    response_body = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
