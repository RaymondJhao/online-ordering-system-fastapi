"""併發下單：驗證高併發下不會超賣。

這是整個專案最值得寫的一個測試。其他測試多半在驗證「功能有沒有做對」，
這裡驗證的是「兩個請求同時進來時，資料庫層的保證是否真的成立」——
而那正是一般作品集的 CRUD 測試碰不到、面試時卻最常被追問的地方。

與其他測試的差異：不能用共用 session 的 `db` fixture。那個 fixture 讓所有
操作跑在同一筆交易裡，天然就不會有併發衝突，測了等於沒測。這裡每個並行的
下單各自使用獨立的連線與交易，真正重現多個 worker 同時處理請求的情況。
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Customer, MenuItem, Merchant, Order
from app.schemas.order import OrderItemCreate
from app.services import order_service
from app.services.stock_service import InsufficientStockError

# 這些資料表會被本檔案清空重建，因此不能與其他測試同時執行
_TABLES = "order_items, orders, idempotency_records, menu_items, coupons, customers, merchants"


@pytest.fixture
async def real_engine() -> AsyncEngine:
    """獨立 engine：本檔案的操作必須真的 commit，才會產生併發競爭。"""
    engine = create_async_engine(get_settings().database_url_str, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def session_factory(real_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=real_engine, expire_on_commit=False)


async def _seed(session_factory, *, stock: int) -> tuple[int, int, int]:
    """建立商家、顧客與一個限量餐點，回傳三者的 id。"""
    async with session_factory() as session:
        merchant = Merchant(name="限量商家", email="limited@test.com", password_hash="x")
        customer = Customer(name="搶購顧客", email="rush@test.com", password_hash="x")
        session.add_all([merchant, customer])
        await session.flush()

        item = MenuItem(
            merchant_id=merchant.id,
            name="限量餐點",
            price=Decimal("100.00"),
            stock=stock,
        )
        session.add(item)
        await session.commit()
        return merchant.id, customer.id, item.id


async def _place_order(session_factory, *, customer_id, merchant_id, item_id, quantity) -> bool:
    """在獨立 session 中下單，回傳是否成功。"""
    async with session_factory() as session:
        try:
            await order_service.create_customer_order(
                session,
                customer_id=customer_id,
                merchant_id=merchant_id,
                items=[OrderItemCreate(menu_item_id=item_id, quantity=quantity)],
                payment_method="ONLINE",
                pickup_time=None,
                table_number=None,
                coupon_code=None,
                idempotency_key=None,
            )
            return True
        except InsufficientStockError:
            return False


async def _final_state(session_factory, item_id: int) -> tuple[int, int]:
    async with session_factory() as session:
        stock = await session.scalar(select(MenuItem.stock).where(MenuItem.id == item_id))
        order_count = await session.scalar(select(text("count(*)")).select_from(Order))
        return stock, order_count


async def test_二十個並行請求搶五份庫存只會成功五筆(session_factory) -> None:
    """庫存 5，同時湧入 20 筆下單，必須恰好成功 5 筆。

    若扣庫存用的是「先 SELECT 再判斷再 UPDATE」，這裡會有多筆請求同時通過
    檢查，成功數會大於 5，庫存也會被扣成負數。
    """
    merchant_id, customer_id, item_id = await _seed(session_factory, stock=5)

    results = await asyncio.gather(
        *(
            _place_order(
                session_factory,
                customer_id=customer_id,
                merchant_id=merchant_id,
                item_id=item_id,
                quantity=1,
            )
            for _ in range(20)
        )
    )

    succeeded = sum(results)
    stock, order_count = await _final_state(session_factory, item_id)

    assert succeeded == 5, f"應恰好成功 5 筆，實際 {succeeded} 筆"
    assert stock == 0, f"庫存應歸零，實際為 {stock}"
    assert order_count == 5, f"應只建立 5 筆訂單，實際 {order_count} 筆"


async def test_每筆訂購兩份時庫存十份只會成功五筆(session_factory) -> None:
    """數量不為 1 時同樣成立：WHERE stock >= :quantity 卡的是實際需求量。"""
    merchant_id, customer_id, item_id = await _seed(session_factory, stock=10)

    results = await asyncio.gather(
        *(
            _place_order(
                session_factory,
                customer_id=customer_id,
                merchant_id=merchant_id,
                item_id=item_id,
                quantity=2,
            )
            for _ in range(15)
        )
    )

    stock, order_count = await _final_state(session_factory, item_id)

    assert sum(results) == 5
    assert stock == 0
    assert order_count == 5


async def test_庫存無法被扣成負數(session_factory) -> None:
    """壓力測試：需求量刻意超過庫存，結束後庫存不可為負。

    即使原子扣減的邏輯出錯，資料庫的 CHECK 約束（stock >= 0）也會擋下，
    這是第二道防線。
    """
    merchant_id, customer_id, item_id = await _seed(session_factory, stock=7)

    await asyncio.gather(
        *(
            _place_order(
                session_factory,
                customer_id=customer_id,
                merchant_id=merchant_id,
                item_id=item_id,
                quantity=3,
            )
            for _ in range(10)
        )
    )

    stock, _ = await _final_state(session_factory, item_id)
    assert stock >= 0, f"庫存被扣成負數：{stock}"
    assert stock == 1, "7 份庫存、每筆 3 份，應成功 2 筆並剩下 1 份"


async def test_相同_Idempotency_Key_的並行請求只會成功一筆(session_factory) -> None:
    """使用者連點兩次、或客戶端逾時重試時，兩個請求可能幾乎同時抵達。

    兩者都會通過「查無此 key」的檢查，接著同時嘗試寫入；unique 約束會讓
    後 commit 的那個失敗，它自己的庫存扣減隨 rollback 撤銷，
    最終只會有一筆訂單、庫存也只被扣一次。
    """
    merchant_id, customer_id, item_id = await _seed(session_factory, stock=50)

    async def place_with_key() -> None:
        async with session_factory() as session:
            await order_service.create_customer_order(
                session,
                customer_id=customer_id,
                merchant_id=merchant_id,
                items=[OrderItemCreate(menu_item_id=item_id, quantity=1)],
                payment_method="ONLINE",
                pickup_time=None,
                table_number=None,
                coupon_code=None,
                idempotency_key="concurrent-key",
            )

    await asyncio.gather(*(place_with_key() for _ in range(5)), return_exceptions=True)

    stock, order_count = await _final_state(session_factory, item_id)

    assert order_count == 1, f"應只建立 1 筆訂單，實際 {order_count} 筆"
    assert stock == 49, f"庫存只能被扣一次，實際剩下 {stock}"
