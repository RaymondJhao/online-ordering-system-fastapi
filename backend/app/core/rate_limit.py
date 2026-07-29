"""以 Redis 實作的滑動視窗限流。

取代舊版的 Flask-Limiter。FastAPI 生態最接近的替代品是 fastapi-limiter，
但它在 0.2 版改成 pyrate_limiter 的薄包裝，API 與多數文件記載的不同；
另一個常見選擇 slowapi 則維護狀況偏弱。這裡的需求只有「每 N 秒最多 M 次」，
自己實作約 60 行、沒有版本斷裂風險，而且演算法可以被完整測試。

**演算法：滑動視窗日誌（sliding window log）**

用一個 Redis sorted set 記錄每次請求的時間戳。判斷時先移除視窗外的舊紀錄，
再看剩下幾筆。相較於固定視窗計數器（INCR + EXPIRE），滑動視窗不會有
「視窗交界處可以在瞬間放行兩倍請求」的問題——固定視窗下，第 59 秒打滿 5 次、
第 61 秒又打滿 5 次，兩秒內實際放行了 10 次。

**為什麼要用 Lua 腳本**

「檢查數量」與「寫入本次紀錄」必須是同一個原子操作，理由與訂單的原子扣庫存
完全相同：分成兩次往返時，多個並行請求會同時通過檢查，導致實際放行量超過上限。
Redis 的 Lua 腳本在單執行緒中完整執行，天然具備原子性。
"""

import time
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis import get_redis

# KEYS[1] = 限流鍵
# ARGV = [現在時間(ms), 視窗長度(ms), 上限次數, 本次請求的唯一識別]
# 回傳 [是否放行, 剩餘可用次數, 需等待毫秒數]
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)

if used >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window - (now - tonumber(oldest[2]))
    return {0, 0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, limit - used - 1, 0}
"""


class RateLimiter:
    """限流依賴。

    用法：`Depends(RateLimiter(times=5, seconds=60, scope="create_order"))`

    識別方式為「來源 IP + scope」，與舊版 Flask-Limiter 的 get_remote_address
    行為一致。改用登入者 id 會更精準（同一個 NAT 後的多位使用者不會互相影響），
    但那要求認證依賴先於限流執行，會讓兩者的順序變成隱性契約；
    目前的規模下不值得換取那份脆弱性。
    """

    def __init__(self, *, times: int, seconds: int, scope: str) -> None:
        self.times = times
        self.window_ms = seconds * 1000
        self.scope = scope

    @staticmethod
    def _client_ip(request: Request) -> str:
        """取得來源 IP。

        Render 之類的平台會把服務放在反向代理之後，此時 request.client.host
        永遠是代理伺服器的位址，直接拿來限流等於對全站共用一個計數器。
        X-Forwarded-For 的第一段才是真正的來源。

        注意這個標頭是可以偽造的——只有在確定服務位於可信代理之後時才該採信。
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def __call__(
        self,
        request: Request,
        response: Response,
        redis: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        if not get_settings().RATE_LIMIT_ENABLED:
            return

        key = f"ratelimit:{self.scope}:{self._client_ip(request)}"
        now_ms = int(time.time() * 1000)

        allowed, remaining, retry_after_ms = await redis.eval(
            _SLIDING_WINDOW_SCRIPT,
            1,
            key,
            now_ms,
            self.window_ms,
            self.times,
            uuid.uuid4().hex,
        )

        response.headers["X-RateLimit-Limit"] = str(self.times)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        if not allowed:
            retry_after = max(1, int(retry_after_ms / 1000) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"請求過於頻繁，請於 {retry_after} 秒後再試",
                # Retry-After 是 RFC 9110 對 429 的建議標頭，
                # 讓客戶端知道該等多久而不是盲目重試
                headers={"Retry-After": str(retry_after)},
            )
