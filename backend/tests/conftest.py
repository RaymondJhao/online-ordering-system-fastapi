"""pytest 共用設定與 fixtures。

與舊版最重要的差異：測試跑在**真實的 Postgres** 上，而非記憶體 SQLite。

舊版的 conftest 刻意用 `sqlite:///:memory:` 以求快速與隔離，但開發環境是 MySQL、
正式環境是 Postgres，三套資料庫的行為並不一致。受影響最大的正是本專案最關鍵的
一段邏輯——原子扣庫存的原生 SQL、Enum 型別、Numeric 精度與交易隔離級別在
SQLite 上的表現無法代表正式環境，等於測試綠燈並不保證線上正確。

資料庫結構由 Alembic 建立而非 `Base.metadata.create_all()`，
如此每次測試都會順帶驗證 migration 本身可以正確 upgrade 與 downgrade。
"""

import subprocess
from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Coupon, Customer, DiscountType, MenuItem, Merchant

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_alembic(*args: str) -> None:
    """以子行程執行 alembic。

    不直接呼叫 alembic.command 是因為 env.py 內部會用 asyncio.run() 建立
    事件迴圈，在 pytest-asyncio 已經啟動迴圈的情境下呼叫會拋
    "asyncio.run() cannot be called from a running event loop"。
    """
    result = subprocess.run(
        ["alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} 失敗：\n{result.stderr}")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """整個測試 session 開始前，把資料庫結構重建到最新版本。

    先 downgrade base 再 upgrade head，順便驗證 migration 的 downgrade
    路徑確實可用——只寫 upgrade 而 downgrade 壞掉的 migration 很常見，
    等到正式環境需要回滾時才發現就太晚了。
    """
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """每個測試建立獨立 engine。

    刻意不用 session scope：pytest-asyncio 預設每個測試各有一個事件迴圈，
    而 async engine 綁定在建立它的迴圈上，跨迴圈共用會出現 ScopeMismatch。
    搭配 NullPool 之後每個測試只多開一條連線，代價可以忽略。
    """
    eng = create_async_engine(get_settings().database_url_str, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """每個測試取得一個獨立 session，結束後整筆交易 rollback。

    測試之間因此完全隔離，不需要在每個測試前後清空資料表。
    session 綁定在外層連線的交易上，並以 create_savepoint 模式加入：
    測試內即使呼叫 commit() 也只是釋放 savepoint，最終仍會被外層 rollback 撤銷。
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def seed_data(db: AsyncSession) -> dict[str, object]:
    """基礎假資料：一個商家、一個顧客、一個餐點、一張優惠券。"""
    merchant = Merchant(
        name="測試商家",
        email="merchant@test.com",
        phone="0900000000",
        address="測試市測試路 1 號",
        password_hash="not-a-real-hash",
    )
    customer = Customer(
        name="測試顧客",
        email="customer@test.com",
        phone="0911111111",
        password_hash="not-a-real-hash",
    )
    db.add_all([merchant, customer])
    await db.flush()

    menu_item = MenuItem(
        merchant_id=merchant.id,
        name="招牌漢堡",
        price=Decimal("120.00"),
        description="測試用品項",
        stock=50,
    )
    coupon = Coupon(
        code="OPEN888",
        discount_type=DiscountType.FIXED,
        discount_value=50,
        merchant_id=merchant.id,
        is_active=True,
    )
    db.add_all([menu_item, coupon])
    await db.flush()

    return {
        "merchant": merchant,
        "customer": customer,
        "menu_item": menu_item,
        "coupon": coupon,
    }
