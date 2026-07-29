"""背景排程、分散式鎖與 API 限流。"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.scheduler import run_with_lock
from app.models import MenuItem, Order, OrderItem, OrderStatus, PaymentStatus
from app.services import maintenance_service
from tests.conftest import auth_headers


async def _make_order(
    db: AsyncSession, seed: dict, *, minutes_ago: int, quantity: int = 5, **overrides
) -> Order:
    menu_item: MenuItem = seed["menu_item"]
    order = Order(
        customer_id=seed["customer"].id,
        merchant_id=seed["merchant"].id,
        total_price=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        **overrides,
    )
    order.order_items.append(
        OrderItem(menu_item_id=menu_item.id, quantity=quantity, price=menu_item.price)
    )
    db.add(order)
    await db.flush()
    return order


# ---------------------------------------------------------------------------
# 排程：取消逾時未付款訂單
# ---------------------------------------------------------------------------


async def test_逾時未付款訂單會被取消(db: AsyncSession, seed_data: dict) -> None:
    order = await _make_order(db, seed_data, minutes_ago=30)

    cancelled = await maintenance_service.cancel_expired_unpaid_orders(db)

    assert order.id in cancelled
    await db.refresh(order)
    assert order.status is OrderStatus.CANCELLED


async def test_取消時會把庫存還回去(db: AsyncSession, seed_data: dict) -> None:
    """舊版最實際的一個缺陷。

    tasks.py 的 docstring 寫「自動轉成 CANCELLED，把庫存釋放回去」，
    但程式碼只有改狀態那一行。排程每跑一次，被取消訂單佔用的庫存就永久消失，
    它宣稱要解決的問題恰恰是它自己造成的。
    """
    menu_item: MenuItem = seed_data["menu_item"]
    original_stock = menu_item.stock

    await _make_order(db, seed_data, minutes_ago=30, quantity=5)
    # 模擬下單時已扣掉的庫存
    menu_item.stock = original_stock - 5
    await db.flush()

    await maintenance_service.cancel_expired_unpaid_orders(db)

    stock = await db.scalar(select(MenuItem.stock).where(MenuItem.id == menu_item.id))
    assert stock == original_stock, "取消訂單必須把庫存還回去"


async def test_未逾時的訂單不受影響(db: AsyncSession, seed_data: dict) -> None:
    order = await _make_order(db, seed_data, minutes_ago=5)

    cancelled = await maintenance_service.cancel_expired_unpaid_orders(db)

    assert order.id not in cancelled
    await db.refresh(order)
    assert order.status is OrderStatus.PENDING


async def test_已付款的訂單不會被取消(db: AsyncSession, seed_data: dict) -> None:
    """付款狀態才是判斷棄單的依據，不是單看時間。"""
    order = await _make_order(db, seed_data, minutes_ago=30, payment_status=PaymentStatus.PAID)

    cancelled = await maintenance_service.cancel_expired_unpaid_orders(db)

    assert order.id not in cancelled
    await db.refresh(order)
    assert order.status is OrderStatus.PENDING


async def test_商家已接單的訂單不會被取消(db: AsyncSession, seed_data: dict) -> None:
    order = await _make_order(db, seed_data, minutes_ago=30, status=OrderStatus.ACCEPTED)

    cancelled = await maintenance_service.cancel_expired_unpaid_orders(db)

    assert order.id not in cancelled


async def test_沒有逾時訂單時不做任何事(db: AsyncSession, seed_data: dict) -> None:
    assert await maintenance_service.cancel_expired_unpaid_orders(db) == []


# ---------------------------------------------------------------------------
# 分散式鎖：多 worker 只執行一次
# ---------------------------------------------------------------------------


async def test_同一輪只有一個_worker_會執行(redis_client: Redis) -> None:
    """舊版的 WERKZEUG_RUN_MAIN 判斷只擋得住開發模式的 reloader。

    正式環境以 gunicorn -w 4 啟動時，四個 worker 各自都會跑一份排程，
    同一批逾時訂單會被處理四次——在會回補庫存的版本裡，那等於憑空多出庫存。
    """
    executions: list[int] = []

    async def job() -> None:
        executions.append(1)

    results = [
        await run_with_lock(redis_client, job_id="test_job", ttl_seconds=30, job=job)
        for _ in range(4)
    ]

    assert results == [True, False, False, False]
    assert len(executions) == 1, "四個 worker 中只有一個該實際執行"


async def test_鎖到期後可再次執行(redis_client: Redis) -> None:
    """TTL 是必要的：持鎖的 worker 若中途被砍掉，沒有 TTL 的鎖會永遠留著，
    之後所有排程都不會再執行。"""
    executed = []

    async def job() -> None:
        executed.append(1)

    assert await run_with_lock(redis_client, job_id="ttl_job", ttl_seconds=1, job=job)
    assert not await run_with_lock(redis_client, job_id="ttl_job", ttl_seconds=1, job=job)

    await redis_client.delete("scheduler:lock:ttl_job")  # 模擬 TTL 到期

    assert await run_with_lock(redis_client, job_id="ttl_job", ttl_seconds=1, job=job)
    assert len(executed) == 2


async def test_不同工作的鎖互不影響(redis_client: Redis) -> None:
    async def noop() -> None:
        return None

    assert await run_with_lock(redis_client, job_id="job_a", ttl_seconds=30, job=noop)
    assert await run_with_lock(redis_client, job_id="job_b", ttl_seconds=30, job=noop)


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------


@pytest.fixture
def rate_limit_on(monkeypatch: pytest.MonkeyPatch):
    """暫時開啟限流。

    其餘測試一律關閉，否則同一分鐘內重複呼叫下單 API 的測試會互相干擾——
    這也是舊版 conftest 設定 RATELIMIT_ENABLED = False 的原因。
    """
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_ENABLED", True)


async def test_超過上限回_429(
    client: AsyncClient,
    customer_session: dict,
    merchant_session: dict,
    merchant_menu_item: dict,
    rate_limit_on,
) -> None:
    """下單限制為每分鐘 5 次，第 6 次應被擋下。"""
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
    }
    headers = auth_headers(customer_session)

    statuses = [
        (await client.post("/api/orders", json=payload, headers=headers)).status_code
        for _ in range(6)
    ]

    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429


async def test_被限流時附帶_Retry_After_標頭(
    client: AsyncClient,
    customer_session: dict,
    merchant_session: dict,
    merchant_menu_item: dict,
    rate_limit_on,
) -> None:
    """RFC 9110 建議 429 回應要告訴客戶端該等多久，而不是讓它盲目重試。"""
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
    }
    headers = auth_headers(customer_session)

    for _ in range(5):
        await client.post("/api/orders", json=payload, headers=headers)

    response = await client.post("/api/orders", json=payload, headers=headers)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


async def test_未達上限時回傳剩餘次數(
    client: AsyncClient,
    customer_session: dict,
    merchant_session: dict,
    merchant_menu_item: dict,
    rate_limit_on,
) -> None:
    response = await client.post(
        "/api/orders",
        json={
            "merchant_id": merchant_session["user"]["id"],
            "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
        },
        headers=auth_headers(customer_session),
    )

    assert response.headers["x-ratelimit-limit"] == "5"
    assert response.headers["x-ratelimit-remaining"] == "4"


async def test_不同端點的限流互不影響(
    client: AsyncClient,
    customer_session: dict,
    merchant_session: dict,
    merchant_menu_item: dict,
    rate_limit_on,
) -> None:
    """scope 不同即為不同的計數器：下單打滿不該影響結帳。"""
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
    }
    headers = auth_headers(customer_session)

    orders = [(await client.post("/api/orders", json=payload, headers=headers)) for _ in range(5)]
    assert (await client.post("/api/orders", json=payload, headers=headers)).status_code == 429

    checkout = await client.post(f"/api/payment/checkout/{orders[0].json()['id']}", headers=headers)
    assert checkout.status_code == 200, "結帳有自己的計數器，不該被下單的限流影響"


async def test_關閉限流時不生效(
    client: AsyncClient,
    customer_session: dict,
    merchant_session: dict,
    merchant_menu_item: dict,
) -> None:
    """預設（測試環境）關閉，連續 8 次下單都應成功。"""
    payload = {
        "merchant_id": merchant_session["user"]["id"],
        "items": [{"menu_item_id": merchant_menu_item["id"], "quantity": 1}],
    }
    headers = auth_headers(customer_session)

    statuses = [
        (await client.post("/api/orders", json=payload, headers=headers)).status_code
        for _ in range(8)
    ]
    assert statuses == [201] * 8


# ---------------------------------------------------------------------------
# 部署設定
# ---------------------------------------------------------------------------


def test_雲端平台的連線字串會自動補上_async_driver() -> None:
    """Render / Heroku / Railway 注入的都是 postgresql:// 或 postgres://。

    直接餵給 async SQLAlchemy 會拋「The asyncio extension requires an async
    driver」，而那個訊息看起來很像「連線字串沒設對」，部署時很容易卡住。
    """
    from app.core.config import Settings

    base = {
        "_env_file": None,
        "SECRET_KEY": "a" * 40,
        "JWT_SECRET_KEY": "b" * 40,
        "REDIS_URL": "redis://localhost:6379/0",
    }

    cases = [
        ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        # 已經是 async driver 的不要重複改寫
        ("postgresql+asyncpg://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
    ]

    for given, expected in cases:
        settings = Settings(**base, DATABASE_URL=given)
        assert settings.database_url_str == expected, given
