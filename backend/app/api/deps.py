"""共用的 FastAPI 依賴。

`OAuth2PasswordBearer` 常被誤以為是「認證器」，其實它只做三件事：

1. 從 Authorization 標頭取出 Bearer token 字串
2. 取不到就回 401
3. 在 OpenAPI 文件註冊 security scheme，讓 Swagger UI 出現 Authorize 按鈕

它的回傳值是一個 `str`，它不知道那字串是 JWT、opaque token 還是亂打的。
把字串變成「已驗證的使用者」的那段邏輯，就是本檔案的 `get_current_user`。
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import TokenError, TokenPayload, TokenType, decode_token
from app.models import Customer, Merchant
from app.services import auth_service
from app.services.token_store import TokenStore

# tokenUrl 指向的端點必須接受 form-encoded 的 username/password，
# Swagger UI 的 Authorize 對話框才能運作。前端實際使用的是 /api/auth/login（JSON）。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]


def get_token_store(redis: RedisClient) -> TokenStore:
    return TokenStore(redis)


TokenStoreDep = Annotated[TokenStore, Depends(get_token_store)]


def _unauthorized(detail: str) -> HTTPException:
    """401 一律附帶 WWW-Authenticate 標頭。

    這是 RFC 6750 對 Bearer token 的要求，也是 client 判斷「該去重新取得
    token」而非「這個帳號沒有權限」的依據。舊版有正確處理，這裡保留。
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_token_payload(
    token: Annotated[str, Depends(oauth2_scheme)],
    store: TokenStoreDep,
) -> TokenPayload:
    """驗證 access token，回傳已解析的內容。

    除了簽章與有效期，還要檢查兩份撤銷名單：
    - 該 token 本身是否已被登出撤銷
    - 其所屬 family 是否已被整條撤銷（登出或偵測到 refresh 重用）
    """
    try:
        payload = decode_token(token, TokenType.ACCESS)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    if await store.is_access_revoked(payload.jti):
        raise _unauthorized("token 已被撤銷")

    if payload.family_id and await store.is_family_revoked(payload.family_id):
        raise _unauthorized("登入階段已失效，請重新登入")

    return payload


TokenPayloadDep = Annotated[TokenPayload, Depends(get_token_payload)]


async def get_current_user(
    payload: TokenPayloadDep,
    db: DbSession,
) -> Customer | Merchant:
    """取得目前登入的使用者。

    每個請求都查一次資料庫，確保帳號被刪除後 token 立即失效。
    若日後這裡成為效能瓶頸，可以改為快取，但那是需要權衡的取捨，
    預設應選擇正確性。
    """
    user = await auth_service.get_user(db, payload.role, payload.subject)
    if user is None:
        raise _unauthorized("使用者不存在")
    return user


CurrentUser = Annotated[Customer | Merchant, Depends(get_current_user)]


def require_role(*allowed_roles: str):
    """產生一個限定角色的依賴。

    用法：`Depends(require_role("merchant"))`

    取代舊版散落在每個路由開頭的
    `if get_jwt().get("role") != "merchant": return jsonify(...), 403`。
    改成依賴之後，權限需求會出現在函式簽章與 OpenAPI 文件上，
    而不是藏在函式內文的第一行。
    """

    async def dependency(payload: TokenPayloadDep) -> TokenPayload:
        if payload.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"此操作僅限 {' 或 '.join(allowed_roles)} 使用",
            )
        return payload

    return dependency
