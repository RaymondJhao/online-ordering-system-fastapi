"""建立可直接操作前端 UI 的測試資料。

取代 Flask 版的 `seed_menu_items.py`。行為刻意保持一致：
帳號、餐點、優惠券都是 get-or-create，可以重複執行而不會撞 unique 約束；
情境訂單則每次都新增一批，方便反覆測試接單流程。

用法：

    python -m scripts.seed                      # 使用預設測試帳號
    python -m scripts.seed shop@example.com     # 指定商家帳號
    python -m scripts.seed --if-empty           # 資料庫已有資料就跳過

`--if-empty` 是為了部署流程設計的：Render 免費方案的 PostgreSQL 每 30 天過期，
重建後需要重新灌入結構與展示資料。把
`alembic upgrade head && python -m scripts.seed --if-empty`
放進 preDeployCommand，重建就只剩「貼上新的連線字串」這一步，
而且每次正常部署都不會重複產生情境訂單。詳見 README 的部署章節。

與舊版的差異：密碼雜湊改由 core/security 處理（model 上不再有 set_password），
資料存取改為 async session。
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import dispose_engine, get_sessionmaker
from app.core.security import hash_password
from app.models import (
    Coupon,
    Customer,
    DiscountType,
    MenuItem,
    Merchant,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)

DEFAULT_MERCHANT_EMAIL = "merchant@test.com"
DEFAULT_CUSTOMER_EMAIL = "customer@test.com"
DEFAULT_PASSWORD = "test1234"  # noqa: S105 - 僅供本機測試資料使用

MENU_ITEMS = [
    {"name": "招牌漢堡", "price": "120.00", "description": "手打牛肉排", "stock": 50},
    {"name": "薯條", "price": "60.00", "description": "現炸", "stock": 50},
    {
        "name": "珍珠奶茶",
        "price": "65.00",
        "description": "已售完，用來測試下架品項",
        "stock": 0,
        "is_active": False,
    },
]


async def get_or_create_merchant(db: AsyncSession, email: str) -> Merchant:
    merchant = await db.scalar(select(Merchant).where(Merchant.email == email))
    if merchant:
        print(f"  商家已存在（id={merchant.id}），沿用現有帳號")
        return merchant

    merchant = Merchant(
        name="測試商家",
        email=email,
        phone="0912345678",
        address="測試市測試路 1 號",
        password_hash=await hash_password(DEFAULT_PASSWORD),
    )
    db.add(merchant)
    await db.flush()
    print(f"  已建立商家 {email} / {DEFAULT_PASSWORD}（id={merchant.id}）")
    return merchant


async def get_or_create_customer(db: AsyncSession, email: str) -> Customer:
    customer = await db.scalar(select(Customer).where(Customer.email == email))
    if customer:
        print(f"  顧客已存在（id={customer.id}），沿用現有帳號")
        return customer

    customer = Customer(
        name="測試顧客",
        email=email,
        phone="0987654321",
        password_hash=await hash_password(DEFAULT_PASSWORD),
    )
    db.add(customer)
    await db.flush()
    print(f"  已建立顧客 {email} / {DEFAULT_PASSWORD}（id={customer.id}）")
    return customer


async def get_or_create_menu_items(db: AsyncSession, merchant: Merchant) -> list[MenuItem]:
    items = []
    for spec in MENU_ITEMS:
        existing = await db.scalar(
            select(MenuItem).where(
                MenuItem.merchant_id == merchant.id, MenuItem.name == spec["name"]
            )
        )
        if existing:
            items.append(existing)
            continue

        item = MenuItem(
            merchant_id=merchant.id,
            name=spec["name"],
            price=Decimal(spec["price"]),
            description=spec["description"],
            stock=spec["stock"],
            is_active=spec.get("is_active", True),
        )
        db.add(item)
        items.append(item)

    await db.flush()
    print(f"  餐點共 {len(items)} 項")
    return items


async def get_or_create_coupon(db: AsyncSession, merchant: Merchant) -> Coupon:
    coupon = await db.scalar(select(Coupon).where(Coupon.code == "OPEN888"))
    if coupon:
        print(f"  優惠券已存在（id={coupon.id}）")
        return coupon

    coupon = Coupon(
        code="OPEN888",
        discount_type=DiscountType.FIXED,
        discount_value=50,
        is_active=True,
        merchant_id=merchant.id,
    )
    db.add(coupon)
    await db.flush()
    print(f"  已建立優惠券 OPEN888（id={coupon.id}）")
    return coupon


async def create_scenario_orders(
    db: AsyncSession, merchant: Merchant, customer: Customer, item: MenuItem
) -> None:
    """建立三種情境訂單，方便直接在 UI 上測試不同流程。"""
    scenarios = [
        ("新單待接單", {"status": OrderStatus.PENDING}),
        (
            "已完成可退款",
            {"status": OrderStatus.COMPLETED, "payment_status": PaymentStatus.PAID},
        ),
        (
            "逾時未付款（供排程測試）",
            {"status": OrderStatus.PENDING, "created_at": datetime.now(UTC) - timedelta(hours=1)},
        ),
    ]

    for label, overrides in scenarios:
        order = Order(
            customer_id=customer.id,
            merchant_id=merchant.id,
            total_price=item.price,
            payment_method=PaymentMethod.ONLINE,
            **overrides,
        )
        order.order_items.append(OrderItem(menu_item_id=item.id, quantity=1, price=item.price))
        db.add(order)

        # 這裡直接建立 model 而不經過 order_service，所以要自己把庫存扣掉。
        #
        # 少了這一行，展示資料會自相矛盾：訂單存在但庫存沒少，而「逾時未付款」
        # 那筆一被排程取消就會**回補**庫存，於是數字比原始設定值還多。
        # （實際部署後就是這樣發現的：設定 50，線上顯示 51。）
        item.stock -= 1

        print(f"  情境訂單：{label}")

    await db.flush()


async def database_is_empty(db: AsyncSession) -> bool:
    """判斷是否為全新的資料庫。

    以「有沒有任何商家」為準：沒有商家就沒有餐點、沒有訂單，
    整個系統等於空的。比逐張表檢查簡單，也不會因為新增資料表而失效。
    """
    return await db.scalar(select(Merchant.id).limit(1)) is None


async def main() -> None:
    parser = argparse.ArgumentParser(description="建立展示用測試資料")
    parser.add_argument(
        "merchant_email",
        nargs="?",
        default=DEFAULT_MERCHANT_EMAIL,
        help="商家帳號，未指定時使用預設值",
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="資料庫已有資料就跳過（供部署流程使用，避免重複建立情境訂單）",
    )
    args = parser.parse_args()

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        if args.if_empty and not await database_is_empty(db):
            print("資料庫已有資料，跳過 seed（--if-empty）")
            await dispose_engine()
            return

        print("建立測試資料…")
        merchant = await get_or_create_merchant(db, args.merchant_email)
        customer = await get_or_create_customer(db, DEFAULT_CUSTOMER_EMAIL)
        items = await get_or_create_menu_items(db, merchant)
        await get_or_create_coupon(db, merchant)
        await create_scenario_orders(db, merchant, customer, items[0])
        await db.commit()

    await dispose_engine()
    print("\n完成。可用以下帳號登入：")
    print(f"  商家 {args.merchant_email} / {DEFAULT_PASSWORD}")
    print(f"  顧客 {DEFAULT_CUSTOMER_EMAIL} / {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
