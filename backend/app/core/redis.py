"""Redis 連線管理。

Redis 在本專案承擔兩件事：

1. JWT 撤銷名單（本 Phase）
2. API 限流（Phase 4，由 fastapi-limiter 使用同一個連線池）

為什麼撤銷名單從資料表搬到 Redis：舊版用 `token_blocklist` 資料表記錄已登出的
jti，但沒有任何清理機制——token 早就過期失效了，紀錄仍留在表裡永久累積，
每次驗證 token 都要對這張只增不減的表做一次查詢。Redis 的 TTL 可以讓紀錄在
token 自然到期的同時消失，查詢也是 O(1) 的記憶體操作。

代價是 Redis 若資料遺失，已撤銷的 token 會「復活」到其自然到期為止。
docker-compose 因此開啟 AOF 持久化；access token 只有 15 分鐘，
真的遺失時的曝險窗口也有限。
"""

from functools import lru_cache

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings


@lru_cache
def get_redis_pool() -> ConnectionPool:
    settings = get_settings()
    return ConnectionPool.from_url(
        settings.redis_url_str,
        decode_responses=True,
        max_connections=20,
        # 連不上 Redis 時不要無限等待，讓請求快速失敗
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def get_redis() -> Redis:
    """FastAPI 依賴：取得 Redis client。

    client 本身是輕量物件，共用底層連線池即可，不需要每次請求重建連線。
    """
    return Redis(connection_pool=get_redis_pool())


async def close_redis() -> None:
    """關閉連線池，供 lifespan 的 shutdown 階段呼叫。"""
    pool = get_redis_pool()
    await pool.aclose()
