"""資料層的行為驗證。

這些測試針對的不是 CRUD 是否可用，而是遷移過程中三類具體風險：

1. 舊版 DateTime 欄位沒有時區、導致背景排程在 Postgres 上會拋 TypeError
2. async SQLAlchemy 的 lazy loading 陷阱（MissingGreenlet）
3. 原子扣庫存與資料庫層約束是否確實生效
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Customer,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    PaymentStatus,
)

# ---------------------------------------------------------------------------
# 1. 時區：舊版的實際缺陷
# ---------------------------------------------------------------------------


async def test_created_at_保留時區資訊(db: AsyncSession, seed_data: dict) -> None:
    """created_at 讀回來必須仍是 timezone-aware。

    舊版欄位定義為 `db.Column(db.DateTime)`（無 timezone=True），寫入時
    Python 端雖然給的是 aware datetime，資料庫仍會把時區丟掉，讀回來變 naive。
    """
    customer: Customer = seed_data["customer"]
    await db.refresh(customer)

    assert customer.created_at.tzinfo is not None, "created_at 應為 timezone-aware"
    assert customer.created_at.utcoffset() is not None


async def test_排程用的時間比較不會拋型別錯誤(db: AsyncSession, seed_data: dict) -> None:
    """重現舊版背景排程在 Postgres 上會失敗的情境。

    tasks.py 的查詢條件是 `Order.created_at < cutoff_time`，其中 cutoff_time
    是 aware datetime。若欄位是 naive，Postgres 會拒絕比較並拋 TypeError，
    整個自動取消棄單的排程等於形同虛設。
    """
    merchant = seed_data["merchant"]
    old_order = Order(
        merchant_id=merchant.id,
        customer_id=seed_data["customer"].id,
        total_price=Decimal("120.00"),
        created_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    db.add(old_order)
    await db.flush()

    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    result = await db.execute(
        select(Order).where(
            Order.status == OrderStatus.PENDING,
            Order.payment_status == PaymentStatus.UNPAID,
            Order.created_at < cutoff,
        )
    )
    expired = result.scalars().all()

    assert len(expired) == 1
    assert expired[0].id == old_order.id


# ---------------------------------------------------------------------------
# 2. async 的 lazy loading 陷阱
# ---------------------------------------------------------------------------


async def test_未指定_eager_load_時存取關聯會拋_MissingGreenlet(
    db: AsyncSession, seed_data: dict
) -> None:
    """證明 async 下的隱式 lazy load 確實會失敗。

    這是遷移期最常見的 runtime 錯誤來源：同樣的程式碼在 Flask（同步）能跑，
    改成 async 之後在存取 order.order_items 的瞬間爆炸。
    """
    order = Order(merchant_id=seed_data["merchant"].id, total_price=Decimal("120.00"))
    db.add(order)
    await db.flush()
    db.expunge(order)

    fetched = await db.get(Order, order.id)
    assert fetched is not None

    with pytest.raises(MissingGreenlet):
        _ = fetched.order_items[0]


async def test_selectinload_可正確載入巢狀關聯(db: AsyncSession, seed_data: dict) -> None:
    """正確做法：查詢時明確 eager load，序列化訂單時才不會觸發隱式 I/O。

    這裡一併涵蓋 routes/order.py 序列化訂單時實際用到的兩層關聯：
    order.order_items 與 order_item.menu_item。
    """
    menu_item: MenuItem = seed_data["menu_item"]
    order = Order(merchant_id=seed_data["merchant"].id, total_price=Decimal("240.00"))
    order.order_items.append(
        OrderItem(menu_item_id=menu_item.id, quantity=2, price=menu_item.price)
    )
    db.add(order)
    await db.flush()
    db.expunge_all()

    result = await db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.order_items).selectinload(OrderItem.menu_item))
    )
    fetched = result.scalar_one()

    assert len(fetched.order_items) == 1
    assert fetched.order_items[0].menu_item.name == "招牌漢堡"
    assert fetched.order_items[0].quantity == 2


async def test_commit_後仍可存取屬性(db: AsyncSession, seed_data: dict) -> None:
    """驗證 expire_on_commit=False 的效果。

    預設值 True 會在 commit 後讓所有屬性過期，下次存取觸發隱式重新查詢；
    在 async 下那次隱式查詢會直接拋 MissingGreenlet。典型症狀是 service
    commit 之後回傳 order，路由層讀 order.id 時整個請求失敗。
    """
    order = Order(merchant_id=seed_data["merchant"].id, total_price=Decimal("120.00"))
    db.add(order)
    await db.commit()

    assert order.id is not None
    assert order.status is OrderStatus.PENDING
    assert order.payment_status is PaymentStatus.UNPAID


# ---------------------------------------------------------------------------
# 3. 庫存與資料庫層約束
# ---------------------------------------------------------------------------


async def test_原子扣庫存在庫存足夠時成功(db: AsyncSession, seed_data: dict) -> None:
    """沿用舊版的原生 SQL：把「檢查庫存」與「扣庫存」合併為單一原子操作。"""
    menu_item: MenuItem = seed_data["menu_item"]

    result = await db.execute(
        text("UPDATE menu_items SET stock = stock - :qty WHERE id = :id AND stock >= :qty"),
        {"qty": 10, "id": menu_item.id},
    )

    assert result.rowcount == 1
    await db.refresh(menu_item)
    assert menu_item.stock == 40


async def test_原子扣庫存在庫存不足時不會扣減(db: AsyncSession, seed_data: dict) -> None:
    """庫存不足時 WHERE 條件不成立，rowcount 為 0，庫存維持不變。

    這正是防止超賣的關鍵：不需要先 SELECT 再判斷，也就沒有兩個請求之間的空隙。
    """
    menu_item: MenuItem = seed_data["menu_item"]

    result = await db.execute(
        text("UPDATE menu_items SET stock = stock - :qty WHERE id = :id AND stock >= :qty"),
        {"qty": 999, "id": menu_item.id},
    )

    assert result.rowcount == 0
    await db.refresh(menu_item)
    assert menu_item.stock == 50


async def test_資料庫拒絕負庫存(db: AsyncSession, seed_data: dict) -> None:
    """CHECK 約束作為第二道防線。

    即使日後有人寫了沒經過原子扣庫存路徑的更新，資料庫仍會擋下。
    """
    menu_item: MenuItem = seed_data["menu_item"]

    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE menu_items SET stock = -1 WHERE id = :id"),
            {"id": menu_item.id},
        )
        await db.flush()


async def test_信箱不可重複註冊(db: AsyncSession, seed_data: dict) -> None:
    duplicate = Customer(
        name="重複的顧客",
        email="customer@test.com",
        password_hash="not-a-real-hash",
    )
    db.add(duplicate)

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_訂單明細記錄下單當下的單價(db: AsyncSession, seed_data: dict) -> None:
    """商家日後調價時，歷史訂單金額必須維持不變。"""
    menu_item: MenuItem = seed_data["menu_item"]
    order = Order(merchant_id=seed_data["merchant"].id, total_price=Decimal("120.00"))
    order.order_items.append(
        OrderItem(menu_item_id=menu_item.id, quantity=1, price=Decimal("120.00"))
    )
    db.add(order)
    await db.flush()

    menu_item.price = Decimal("150.00")
    await db.flush()

    assert order.order_items[0].price == Decimal("120.00")
