"""一次性測試資料腳本：確保有一組可登入的測試商家／顧客／餐點／優惠券，並在最後
自動建立三種情境訂單，方便直接打開前端 UI 測試「新單接單」「拒單原因顯示（顧客端）」
「已完成訂單退款／作廢（商家端）」。可重複執行：商家、顧客、餐點、優惠券都是
get-or-create，不會產生重複帳號或撞 IntegrityError；情境訂單則每次執行都會新增一批，
方便反覆測試接單流程。

用法：
    python seed_menu_items.py                  # 使用預設測試商家帳號
    python seed_menu_items.py <merchant_email>  # 指定已存在（或要新建）的商家帳號
"""

import sys

from app import create_app
from app.extensions import db
from app.models import (
    Coupon,
    Customer,
    DiscountType,
    Merchant,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)

DEFAULT_MERCHANT_EMAIL = "merchant@test.com"
DEFAULT_MERCHANT_PASSWORD = "test1234"
DEFAULT_CUSTOMER_EMAIL = "customer@test.com"
DEFAULT_CUSTOMER_PASSWORD = "test1234"

MENU_ITEM_SPECS = [
    {"name": "招牌漢堡", "price": 120, "description": "測試用品項", "stock": 50, "is_active": True},
    {"name": "薯條", "price": 60, "description": "測試用品項", "stock": 50, "is_active": True},
    {"name": "珍珠奶茶", "price": 65, "description": "測試用品項，情境二拒單訂單會用到這一項", "stock": 0, "is_active": False},
]


def get_or_create_merchant(email):
    merchant = Merchant.query.filter_by(email=email).first()
    if merchant is not None:
        print(f"商家 email={email} 已存在（id={merchant.id}），沿用現有帳號，密碼不變更")
        return merchant

    merchant = Merchant(name="測試商家", email=email, phone="0912345678", address="測試市測試路 1 號")
    merchant.set_password(DEFAULT_MERCHANT_PASSWORD)
    db.session.add(merchant)
    db.session.commit()
    print(f"已建立測試商家：email={email}  password={DEFAULT_MERCHANT_PASSWORD}（id={merchant.id}）")
    return merchant


def get_or_create_customer(email):
    customer = Customer.query.filter_by(email=email).first()
    if customer is not None:
        print(f"顧客 email={email} 已存在（id={customer.id}），沿用現有帳號，密碼不變更")
        return customer

    customer = Customer(name="測試顧客", email=email, phone="0987654321")
    customer.set_password(DEFAULT_CUSTOMER_PASSWORD)
    db.session.add(customer)
    db.session.commit()
    print(f"已建立測試顧客：email={email}  password={DEFAULT_CUSTOMER_PASSWORD}（id={customer.id}）")
    return customer


def get_or_create_menu_items(merchant):
    existing_by_name = {
        item.name: item for item in MenuItem.query.filter_by(merchant_id=merchant.id).all()
    }

    items = []
    created_any = False
    for spec in MENU_ITEM_SPECS:
        item = existing_by_name.get(spec["name"])
        if item is None:
            item = MenuItem(merchant_id=merchant.id, **spec)
            db.session.add(item)
            created_any = True
        items.append(item)

    if created_any:
        db.session.commit()

    print("目前商家的 MenuItem：")
    for item in items:
        print(
            f"  id={item.id}  name={item.name}  price={item.price}  "
            f"stock={item.stock}  is_active={item.is_active}"
        )
    return items


def get_or_create_coupon(merchant):
    # code 欄位是全域唯一，重複執行這支腳本時直接略過，避免撞 IntegrityError
    coupon = Coupon.query.filter_by(code="OPEN888").first()
    if coupon is None:
        coupon = Coupon(
            code="OPEN888",
            discount_type=DiscountType.FIXED,
            discount_value=50,
            merchant_id=merchant.id,
            is_active=True,
        )
        db.session.add(coupon)
        db.session.commit()
        print(f"已新增測試優惠券：code={coupon.code}  discount_type={coupon.discount_type.value}  discount_value={coupon.discount_value}")
    else:
        print(f"測試優惠券 code={coupon.code} 已存在，略過建立")
    return coupon


def build_scenario_order(merchant, customer, menu_item, quantity, *, status, payment_status, reject_reason=None):
    """建立一筆訂單與對應的 OrderItem。透過 order.order_items.append(...) 讓 SQLAlchemy
    自行處理 order_id 外鍵（等同 app/routes/order.py 建單時使用的寫法），
    不需要手動指定 order_id，也不會有 flush 順序上的外鍵錯誤。"""
    unit_price = menu_item.price
    order = Order(
        customer_id=customer.id,
        merchant_id=merchant.id,
        total_price=unit_price * quantity,
        status=status,
        payment_status=payment_status,
        payment_method=PaymentMethod.ONLINE,
        reject_reason=reject_reason,
    )
    order.order_items.append(
        OrderItem(menu_item_id=menu_item.id, quantity=quantity, price=unit_price)
    )
    db.session.add(order)
    return order


def create_scenario_orders(merchant, customer, items):
    burger, fries, bubble_tea = items

    orders = [
        # 情境一：待接單 — 商家大螢幕一打開就有新單可以按「接單」
        build_scenario_order(
            merchant, customer, burger, quantity=2,
            status=OrderStatus.PENDING, payment_status=PaymentStatus.UNPAID,
        ),
        # 情境二：已拒單附原因 — 用來測試顧客端「訂單已取消，店家回覆：...」的紅字顯示
        build_scenario_order(
            merchant, customer, bubble_tea, quantity=1,
            status=OrderStatus.REJECTED, payment_status=PaymentStatus.UNPAID,
            reject_reason="抱歉，今日珍珠已售完",
        ),
        # 情境三：已付款、已完成 — 用來測試商家大螢幕的「退款」功能
        # （後端 ALLOWED_TRANSITIONS 規定 REFUNDED 只能從 COMPLETED 轉入，
        # 所以這裡固定用 COMPLETED，而不是 ACCEPTED，才能實際點到退款按鈕）
        build_scenario_order(
            merchant, customer, fries, quantity=3,
            status=OrderStatus.COMPLETED, payment_status=PaymentStatus.PAID,
        ),
    ]
    db.session.commit()

    print("已建立以下情境訂單：")
    for order in orders:
        print(
            f"  Order id={order.id}  status={order.status.value}  "
            f"payment_status={order.payment_status.value}  "
            f"reject_reason={order.reject_reason!r}"
        )
    return orders


merchant_email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MERCHANT_EMAIL

app = create_app()
with app.app_context():
    merchant = get_or_create_merchant(merchant_email)
    customer = get_or_create_customer(DEFAULT_CUSTOMER_EMAIL)
    items = get_or_create_menu_items(merchant)
    get_or_create_coupon(merchant)
    create_scenario_orders(merchant, customer, items)

    print()
    print("測試帳號：")
    print(f"  商家登入：email={merchant.email}（若為腳本新建，密碼為 {DEFAULT_MERCHANT_PASSWORD}）")
    print(f"  顧客登入：email={customer.email}（若為腳本新建，密碼為 {DEFAULT_CUSTOMER_PASSWORD}）")
