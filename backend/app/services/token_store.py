"""JWT 狀態的 Redis 儲存層。

JWT 本身是無狀態的：伺服器不保存任何紀錄，只靠簽章驗證。這帶來擴展性，
但也帶來一個常見的面試題——「無狀態的 token 要怎麼登出？」

答案是必須引入最小限度的狀態。本模組保存三種紀錄，全部帶 TTL，
在 token 自然到期時一併消失，不需要額外的清理排程：

    revoked:access:{jti}    已撤銷的 access token（登出、family 撤銷）
    refresh:active:{jti}    目前有效的 refresh token，值為所屬 family
    revoked:family:{fam}    已整條撤銷的 family（偵測到重用時寫入）

refresh 採「白名單」而非黑名單：只有被明確記錄過、且尚未被用掉的 refresh token
才算數。這是重用偵測能成立的前提——一個簽章正確但不在名單上的 refresh token，
代表它要嘛已經被輪替掉、要嘛是偽造的，兩種都該視為異常。
"""

from redis.asyncio import Redis

_ACCESS_REVOKED = "revoked:access:{jti}"
_REFRESH_ACTIVE = "refresh:active:{jti}"
_FAMILY_REVOKED = "revoked:family:{family_id}"


class TokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # --- access token ---

    async def revoke_access(self, jti: str, ttl_seconds: int) -> None:
        """把 access token 加入撤銷名單。

        TTL 設為 token 的剩餘壽命：紀錄只需要存活到 token 自然失效為止，
        之後即使紀錄消失，token 本身也已經無法通過 exp 檢查。
        """
        if ttl_seconds <= 0:
            return
        await self._redis.set(_ACCESS_REVOKED.format(jti=jti), "1", ex=ttl_seconds)

    async def is_access_revoked(self, jti: str) -> bool:
        return await self._redis.exists(_ACCESS_REVOKED.format(jti=jti)) == 1

    # --- refresh token ---

    async def register_refresh(self, jti: str, family_id: str, ttl_seconds: int) -> None:
        """把新簽發的 refresh token 加入有效名單。"""
        if ttl_seconds <= 0:
            return
        await self._redis.set(_REFRESH_ACTIVE.format(jti=jti), family_id, ex=ttl_seconds)

    async def consume_refresh(self, jti: str) -> str | None:
        """取用一個 refresh token：回傳其 family 並同時把它移出有效名單。

        用 GETDEL 而非「先 GET 再 DEL」：兩個動作之間若有第二個請求插入，
        會出現兩個請求都拿到同一個 token 並各自輪替出新 token 的競態。
        GETDEL 是單一原子操作，只有一個請求會拿到值。
        """
        return await self._redis.getdel(_REFRESH_ACTIVE.format(jti=jti))

    # --- family ---

    async def revoke_family(self, family_id: str, ttl_seconds: int) -> None:
        """撤銷整條 family。

        呼叫時機是偵測到 refresh token 重用——代表 token 已經外洩，
        無法判斷目前持有者是使用者本人還是攻擊者，因此讓雙方都失效，
        強制重新登入。
        """
        if ttl_seconds <= 0:
            return
        await self._redis.set(_FAMILY_REVOKED.format(family_id=family_id), "1", ex=ttl_seconds)

    async def is_family_revoked(self, family_id: str) -> bool:
        return await self._redis.exists(_FAMILY_REVOKED.format(family_id=family_id)) == 1
