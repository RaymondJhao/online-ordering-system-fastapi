"""背景排程。

舊版用 `BackgroundScheduler`（獨立執行緒）並在 `create_app()` 裡以
`WERKZEUG_RUN_MAIN` 判斷是否為 reloader 的子行程，避免排程被啟動兩次。

那段判斷只解決了「開發模式下 werkzeug reloader 開兩個 process」的問題，
**擋不住正式環境的多 worker**：Render 上以 `gunicorn -w 4` 啟動時，
四個 worker 各自都會啟動一份排程，同一批逾時訂單會被處理四次。
在只改狀態的舊版實作下這還算無害，但一旦排程要回補庫存，
重複執行就會把庫存加回四次——多出來的庫存是憑空生出來的。

這裡改用兩層防護：

1. `AsyncIOScheduler` 跑在應用程式既有的事件迴圈上，由 lifespan 管理生命週期，
   不再需要任何關於 reloader 的猜測
2. 每次執行前先取得一把 Redis 分散式鎖，只有搶到鎖的那個 worker 會真的執行
"""

import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.redis import get_redis
from app.services import maintenance_service

logger = logging.getLogger(__name__)

_LOCK_KEY = "scheduler:lock:{job_id}"


async def run_with_lock(
    redis: Redis, *, job_id: str, ttl_seconds: int, job: Callable[[], Awaitable[None]]
) -> bool:
    """搶到鎖才執行，回傳是否實際執行。

    `SET key value NX EX ttl` 是單一原子操作：只有第一個送出這個指令的 worker
    會成功，其餘會拿到 None。TTL 是必要的——沒有它，持有鎖的 worker 若在執行
    途中被砍掉，鎖會永遠留著，之後所有排程都不會再執行。

    TTL 應該設得比工作預期耗時長、但比執行間隔短，這樣既不會讓同一輪重複執行，
    也不會擋到下一輪。
    """
    lock_key = _LOCK_KEY.format(job_id=job_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=ttl_seconds)

    if not acquired:
        logger.debug("排程 %s 已由其他 worker 執行，本次略過", job_id)
        return False

    try:
        await job()
    finally:
        # 刻意不在結束時刪除鎖。若立刻釋放，另一個 worker 的排程可能在同一秒
        # 觸發並再跑一次；讓鎖自然到期才能確保每個間隔內只執行一次。
        pass

    return True


async def _cancel_expired_orders_job() -> None:
    """排程實際執行的工作：在自己的 session 中取消逾時訂單。

    排程不在請求生命週期內，沒有 `Depends(get_db)` 可用，
    因此要自行從 sessionmaker 取得 session 並負責關閉。
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        await maintenance_service.cancel_expired_unpaid_orders(session)


def create_scheduler() -> AsyncIOScheduler:
    """建立並設定排程器，但不啟動。"""
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def job() -> None:
        await run_with_lock(
            get_redis(),
            job_id="cancel_expired_orders",
            # 鎖的存活時間略短於執行間隔，避免擋到下一輪
            ttl_seconds=max(1, settings.SCHEDULER_INTERVAL_SECONDS - 5),
            job=_cancel_expired_orders_job,
        )

    scheduler.add_job(
        job,
        trigger="interval",
        seconds=settings.SCHEDULER_INTERVAL_SECONDS,
        id="cancel_expired_orders",
        replace_existing=True,
        # 服務重啟後可能累積多個錯過的觸發時間，只補跑一次即可
        coalesce=True,
        max_instances=1,
    )
    return scheduler
