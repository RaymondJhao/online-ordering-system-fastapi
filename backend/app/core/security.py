"""密碼雜湊與 JWT 簽發／驗證。

取代舊版的 Flask-Bcrypt 與 Flask-JWT-Extended。這一層是「自己實作」的部分——
FastAPI 的 `OAuth2PasswordBearer` 只負責從 Authorization 標頭取出 token 字串，
以及在 OpenAPI 文件中宣告 security scheme；token 長什麼樣、怎麼簽、怎麼驗，
完全由應用程式決定。

安全性上刻意處理的幾點：

- `jwt.decode` 明確指定 algorithms，避免 algorithm confusion 攻擊
- token 帶 `typ` 欄位並在驗證時檢查，避免 refresh token 被當 access token 使用
- bcrypt 在 threadpool 執行，不阻塞 event loop
- 驗證失敗一律回傳同一種例外，不洩漏「是簽章錯還是過期」以外的細節
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import anyio.to_thread
import bcrypt
import jwt

from app.core.config import get_settings

# bcrypt 只處理前 72 個位元組，較新版本遇到超長密碼會直接拋 ValueError。
# 這裡先用 SHA-256 把密碼壓成固定長度再交給 bcrypt，如此任意長度的密碼都能
# 完整參與雜湊，也不會有「前 72 位元組相同即視為同一組密碼」的問題。
_BCRYPT_MAX_BYTES = 72


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """token 無效的統稱：格式錯誤、簽章不符、過期、型別不符皆屬之。"""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """已驗證的 token 內容。"""

    subject: int
    role: str
    jti: str
    token_type: TokenType
    family_id: str | None
    expires_at: datetime

    @property
    def seconds_until_expiry(self) -> int:
        """距離到期還有幾秒，用來設定撤銷紀錄的 TTL。

        已過期時回傳 0；撤銷一個已過期的 token 沒有意義。
        """
        delta = (self.expires_at - datetime.now(UTC)).total_seconds()
        return max(int(delta), 0)


# ---------------------------------------------------------------------------
# 密碼
# ---------------------------------------------------------------------------


def _prehash(password: str) -> bytes:
    """把任意長度的密碼壓成 bcrypt 能完整處理的長度。"""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return digest[:_BCRYPT_MAX_BYTES]


def _hash_password_sync(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def _verify_password_sync(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except ValueError:
        # 資料庫裡的雜湊格式損毀時，視為驗證失敗而非讓請求 500
        return False


async def hash_password(password: str) -> str:
    """雜湊密碼。

    bcrypt 是刻意設計成慢的 CPU 密集運算（約 100~300ms）。在 `async def` 路由裡
    直接呼叫會卡住整個 event loop，讓所有並行請求一起等待——這比 Flask 的
    同步模型更糟，因為 Flask 至少每個 worker 各自處理一個請求。
    丟到 threadpool 執行才能讓其他請求繼續。
    """
    return await anyio.to_thread.run_sync(_hash_password_sync, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await anyio.to_thread.run_sync(_verify_password_sync, password, password_hash)


# 用於「帳號不存在」時的假驗證，見 auth_service.authenticate。
# 模組載入時計算一次，內容不重要，只需要是合法的 bcrypt 雜湊。
DUMMY_PASSWORD_HASH = _hash_password_sync(secrets.token_urlsafe(32))


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def _create_token(
    *,
    subject: int,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    family_id: str | None = None,
) -> tuple[str, str]:
    """簽發 token，回傳 (token 字串, jti)。"""
    settings = get_settings()
    now = datetime.now(UTC)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "jti": jti,
        "typ": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    if family_id is not None:
        payload["fam"] = family_id

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_access_token(subject: int, role: str, family_id: str) -> tuple[str, str]:
    """簽發 access token。

    access token 同樣帶上 family_id，登出時才能只憑 Authorization 標頭
    就撤銷整條 family。否則使用者登出後，攻擊者手上的 refresh token
    仍可換出新的 access token，登出等於沒有效果。
    """
    settings = get_settings()
    return _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        family_id=family_id,
    )


def create_refresh_token(subject: int, role: str, family_id: str) -> tuple[str, str]:
    settings = get_settings()
    return _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        family_id=family_id,
    )


def new_family_id() -> str:
    """建立一條 token family 的識別碼。

    一次登入產生一條 family，之後每次 refresh 輪替出的新 token 都沿用同一個
    family_id。偵測到重用時就是靠這個值一次撤銷整條鏈上的所有 token。
    """
    return str(uuid.uuid4())


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """驗證並解析 token。

    `algorithms` 一定要明確指定。若省略或接受 token 自帶的 alg，攻擊者可以把
    header 改成 `{"alg": "none"}` 送出未簽章的 token，或在使用非對稱金鑰時
    把 RS256 改成 HS256、拿公鑰當 HMAC 密鑰簽出合法 token。
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token 已過期") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token 無效") from exc

    # 沒有這道檢查，refresh token 就能直接當 access token 用來存取受保護資源，
    # 等於把 15 分鐘的曝險窗口放大成 7 天。
    if claims.get("typ") != expected_type.value:
        raise TokenError("token 型別不符")

    try:
        subject = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("token 的 sub 欄位格式錯誤") from exc

    role = claims.get("role")
    if not isinstance(role, str):
        raise TokenError("token 缺少 role")

    return TokenPayload(
        subject=subject,
        role=role,
        jti=claims["jti"],
        token_type=expected_type,
        family_id=claims.get("fam"),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
