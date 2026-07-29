"""認證商業邏輯。

路由層只負責 HTTP 的輸入輸出，實際的判斷都在這裡，因此可以不透過 HTTP client
直接做單元測試。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_family_id,
    verify_password,
)
from app.models import Customer, Merchant
from app.services.token_store import TokenStore

# 兩種角色分別存在不同資料表，因此需要一張對照表決定要查哪一張
ROLE_MODELS: dict[str, type[Customer] | type[Merchant]] = {
    "customer": Customer,
    "merchant": Merchant,
}


class AuthError(Exception):
    """認證流程的預期失敗，由路由層轉為 401/400。"""


class EmailAlreadyRegisteredError(AuthError):
    pass


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 規範欄位，非密碼


async def get_user(db: AsyncSession, role: str, user_id: int) -> Customer | Merchant | None:
    model = ROLE_MODELS.get(role)
    if model is None:
        return None
    return await db.get(model, user_id)


async def _get_user_by_email(db: AsyncSession, role: str, email: str) -> Customer | Merchant | None:
    model = ROLE_MODELS[role]
    result = await db.execute(select(model).where(model.email == email))
    return result.scalar_one_or_none()


async def register(
    db: AsyncSession,
    *,
    role: str,
    name: str,
    email: str,
    password: str,
    phone: str | None = None,
    address: str | None = None,
) -> Customer | Merchant:
    if await _get_user_by_email(db, role, email) is not None:
        raise EmailAlreadyRegisteredError("此信箱已被註冊")

    password_hash = await hash_password(password)

    user: Customer | Merchant
    if role == "customer":
        user = Customer(name=name, email=email, phone=phone, password_hash=password_hash)
    else:
        user = Merchant(
            name=name,
            email=email,
            phone=phone,
            address=address,
            password_hash=password_hash,
        )

    db.add(user)
    await db.commit()
    return user


async def authenticate(
    db: AsyncSession, *, role: str, email: str, password: str
) -> Customer | Merchant:
    """驗證帳號密碼，失敗時一律拋出同一種錯誤。

    帳號不存在時仍然執行一次 bcrypt 比對（對一組固定的假雜湊），目的是讓
    「帳號不存在」與「密碼錯誤」兩條路徑耗時相近。否則攻擊者只要比較回應時間，
    就能列舉出哪些信箱有註冊過——這類使用者列舉是實務上常見的資訊洩漏。
    """
    user = await _get_user_by_email(db, role, email)
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH

    is_valid = await verify_password(password, password_hash)

    if user is None or not is_valid:
        raise AuthError("信箱或密碼錯誤")

    return user


async def issue_token_pair(
    store: TokenStore, *, user_id: int, role: str, family_id: str | None = None
) -> TokenPair:
    """簽發一組 access + refresh token。

    登入時不帶 family_id，會開啟一條新的 family；
    refresh 輪替時沿用原本的 family_id，讓整條鏈可以被一起撤銷。
    """
    settings = get_settings()
    family = family_id or new_family_id()

    access_token, _ = create_access_token(user_id, role, family)
    refresh_token, refresh_jti = create_refresh_token(user_id, role, family)

    await store.register_refresh(
        refresh_jti,
        family,
        ttl_seconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


async def rotate_refresh_token(store: TokenStore, *, refresh_token: str) -> TokenPair:
    """以 refresh token 換發新的一組 token，並偵測重用。

    流程：

    1. 驗證簽章與型別
    2. family 已被撤銷 → 拒絕
    3. 從有效名單原子取用該 jti
       - 取不到 → **重用偵測命中**：這個 token 要嘛已被輪替過、要嘛是偽造的。
         合法使用者的 client 不會拿舊 token 再送一次，因此合理推論是 token
         已經外洩且攻擊者正在使用。撤銷整條 family，強制重新登入。
       - 取得成功 → 舊 token 就此失效，簽發新的一組
    """
    settings = get_settings()
    refresh_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    try:
        payload = decode_token(refresh_token, TokenType.REFRESH)
    except TokenError as exc:
        raise AuthError(str(exc)) from exc

    if payload.family_id is None:
        raise AuthError("refresh token 缺少 family 資訊")

    if await store.is_family_revoked(payload.family_id):
        raise AuthError("登入階段已失效，請重新登入")

    consumed_family = await store.consume_refresh(payload.jti)

    if consumed_family is None:
        # 重用偵測命中
        await store.revoke_family(payload.family_id, ttl_seconds=refresh_ttl)
        raise AuthError("偵測到 refresh token 重複使用，該登入階段的所有 token 已失效")

    return await issue_token_pair(
        store,
        user_id=payload.subject,
        role=payload.role,
        family_id=consumed_family,
    )


async def logout(store: TokenStore, *, access_jti: str, access_ttl: int, family_id: str) -> None:
    """登出：撤銷目前的 access token，並讓整條 family 的 refresh 失效。

    只撤銷 access token 是不夠的——攻擊者若同時持有 refresh token，
    仍可在下一秒換出新的 access token。
    """
    settings = get_settings()
    await store.revoke_access(access_jti, ttl_seconds=access_ttl)
    await store.revoke_family(
        family_id, ttl_seconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
