"""認證層的安全性驗證。

這些測試對應的是「面試官會追問什麼」而不只是「功能有沒有壞」：
偽造 token 擋不擋得住、登出後真的失效嗎、refresh token 外洩會怎樣。
"""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    TokenType,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

settings = get_settings()

# 攻擊者持有的錯誤密鑰。長度刻意超過 32 位元組，否則 PyJWT 會發出
# InsecureKeyLengthWarning，讓測試輸出出現與被測行為無關的雜訊。
_ATTACKER_KEY = "attacker-key-that-is-not-the-real-secret-and-long-enough"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _forge(claims: dict, key: str | None = None, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key or settings.JWT_SECRET_KEY, algorithm=algorithm)


def _base_claims(**overrides) -> dict:
    now = datetime.now(UTC)
    claims = {
        "sub": "1",
        "role": "customer",
        "jti": "forged-jti",
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    claims.update(overrides)
    return claims


# ---------------------------------------------------------------------------
# 1. 偽造與竄改
# ---------------------------------------------------------------------------


async def test_過期的_token_會被拒絕(client: AsyncClient) -> None:
    expired = _forge(
        _base_claims(
            iat=datetime.now(UTC) - timedelta(hours=2),
            exp=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    response = await client.get("/api/auth/me", headers=_auth(expired))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "過期" in response.json()["detail"]


async def test_簽章被竄改的_token_會被拒絕(client: AsyncClient) -> None:
    """用錯誤的密鑰簽出的 token 必須無法通過驗證。"""
    forged = _forge(_base_claims(), key=_ATTACKER_KEY)
    response = await client.get("/api/auth/me", headers=_auth(forged))

    assert response.status_code == 401


async def test_payload_被竄改後簽章驗證失敗(client: AsyncClient, logged_in_customer) -> None:
    """把合法 token 的 role 改成 merchant 之後，簽章就對不上了。"""
    token = logged_in_customer["access_token"]
    header, _payload, signature = token.split(".")

    tampered_claims = jwt.decode(token, options={"verify_signature": False})
    tampered_claims["role"] = "merchant"
    tampered_payload = _forge(tampered_claims, key=_ATTACKER_KEY).split(".")[1]

    response = await client.get(
        "/api/auth/me", headers=_auth(f"{header}.{tampered_payload}.{signature}")
    )
    assert response.status_code == 401


async def test_alg_none_的未簽章_token_會被拒絕(client: AsyncClient) -> None:
    """algorithm confusion 攻擊最經典的形式。

    攻擊者把 header 改成 {"alg": "none"} 並移除簽章。若驗證時沒有明確指定
    algorithms，某些函式庫會直接接受。security.py 的 jwt.decode 有寫明
    algorithms=[HS256]，因此這裡必定失敗。
    """
    unsigned = jwt.encode(_base_claims(), key="", algorithm="none")
    response = await client.get("/api/auth/me", headers=_auth(unsigned))

    assert response.status_code == 401


async def test_refresh_token_不能當作_access_token_使用(client: AsyncClient) -> None:
    """typ 欄位檢查。

    沒有這道檢查，攻擊者拿到 refresh token 就能直接存取受保護資源，
    等於把 15 分鐘的曝險窗口放大成 7 天。
    """
    refresh_token, _ = create_refresh_token(1, "customer", "some-family")
    response = await client.get("/api/auth/me", headers=_auth(refresh_token))

    assert response.status_code == 401
    assert "型別" in response.json()["detail"]


async def test_access_token_不能用來換發(client: AsyncClient, logged_in_customer) -> None:
    """反方向同理：access token 不能拿去 /refresh。"""
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": logged_in_customer["access_token"]},
    )
    assert response.status_code == 401


async def test_缺少_Authorization_標頭回_401(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. refresh 輪替與重用偵測
# ---------------------------------------------------------------------------


async def test_refresh_會輪替出全新的一組_token(client: AsyncClient, logged_in_customer) -> None:
    old_refresh = logged_in_customer["refresh_token"]

    response = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})

    assert response.status_code == 200
    body = response.json()
    assert body["refresh_token"] != old_refresh, "refresh token 必須輪替"
    assert body["access_token"] != logged_in_customer["access_token"]


async def test_舊的_refresh_token_輪替後立即失效(client: AsyncClient, logged_in_customer) -> None:
    old_refresh = logged_in_customer["refresh_token"]
    await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})

    response = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 401


async def test_重用舊_refresh_token_會撤銷整條_family(
    client: AsyncClient, logged_in_customer
) -> None:
    """核心情境：token 外洩。

    使用者正常換發（token A → B），攻擊者手上留著已失效的 A 並嘗試使用。
    系統偵測到 A 被重用，判定這條 family 已經外洩，連合法的 B 一併撤銷，
    迫使雙方都重新登入。犧牲一次使用者體驗，換取阻斷攻擊者的持續存取。
    """
    token_a = logged_in_customer["refresh_token"]

    first = await client.post("/api/auth/refresh", json={"refresh_token": token_a})
    token_b = first.json()["refresh_token"]

    # 攻擊者重用已失效的 A
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": token_a})
    assert reuse.status_code == 401
    assert "重複使用" in reuse.json()["detail"]

    # 合法使用者手上的 B 也一併失效
    victim = await client.post("/api/auth/refresh", json={"refresh_token": token_b})
    assert victim.status_code == 401, "偵測到重用後，整條 family 都應失效"


async def test_family_撤銷後既有的_access_token_也失效(
    client: AsyncClient, logged_in_customer
) -> None:
    token_a = logged_in_customer["refresh_token"]
    first = await client.post("/api/auth/refresh", json={"refresh_token": token_a})
    new_access = first.json()["access_token"]

    assert (await client.get("/api/auth/me", headers=_auth(new_access))).status_code == 200

    await client.post("/api/auth/refresh", json={"refresh_token": token_a})  # 觸發重用偵測

    response = await client.get("/api/auth/me", headers=_auth(new_access))
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. 登出
# ---------------------------------------------------------------------------


async def test_登出後_access_token_立即失效(client: AsyncClient, logged_in_customer) -> None:
    """JWT 無狀態卻要能登出，靠的就是這份 Redis 撤銷名單。"""
    access = logged_in_customer["access_token"]
    assert (await client.get("/api/auth/me", headers=_auth(access))).status_code == 200

    logout = await client.post("/api/auth/logout", headers=_auth(access))
    assert logout.status_code == 200

    response = await client.get("/api/auth/me", headers=_auth(access))
    assert response.status_code == 401


async def test_登出後_refresh_token_也失效(client: AsyncClient, logged_in_customer) -> None:
    """只撤銷 access token 是不夠的。

    若 refresh token 仍然有效，攻擊者下一秒就能換出新的 access token，
    登出等於沒有作用。
    """
    await client.post("/api/auth/logout", headers=_auth(logged_in_customer["access_token"]))

    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": logged_in_customer["refresh_token"]},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. 密碼
# ---------------------------------------------------------------------------


async def test_密碼以_bcrypt_雜湊而非明文儲存() -> None:
    password = "password123"
    hashed = await hash_password(password)

    assert hashed != password
    assert hashed.startswith("$2b$"), "應為 bcrypt 格式"
    assert await verify_password(password, hashed)
    assert not await verify_password("wrong-password", hashed)


async def test_超過_72_位元組的密碼仍可正確驗證() -> None:
    """bcrypt 只處理前 72 位元組，較新版本遇到超長輸入會直接拋 ValueError。

    security.py 先用 SHA-256 壓縮，因此任意長度都能完整參與雜湊，
    也不會出現「前 72 位元組相同即視為同一組密碼」的問題。
    """
    long_password = "a" * 100
    hashed = await hash_password(long_password)

    assert await verify_password(long_password, hashed)
    assert not await verify_password("a" * 99 + "b", hashed)


async def test_bcrypt_不會阻塞_event_loop() -> None:
    """bcrypt 是 CPU 密集運算，必須在 threadpool 執行。

    這裡同時發出多個雜湊請求：若它們在 event loop 上序列執行，總時間會接近
    單次耗時的倍數；正確丟到 threadpool 時則會並行，總時間明顯小於總和。
    """
    import asyncio

    start = time.perf_counter()
    await hash_password("measure-single-run")
    single = time.perf_counter() - start

    start = time.perf_counter()
    await asyncio.gather(*(hash_password(f"concurrent-{i}") for i in range(4)))
    concurrent = time.perf_counter() - start

    assert concurrent < single * 4, (
        f"4 次並行雜湊耗時 {concurrent:.3f}s，單次為 {single:.3f}s，"
        "看起來是在 event loop 上序列執行"
    )


async def test_帳號不存在與密碼錯誤的回應無法區分(client: AsyncClient, registered_customer) -> None:
    """避免使用者列舉：兩種失敗必須回傳相同的狀態碼與訊息。"""
    wrong_password = await client.post(
        "/api/auth/login",
        json={
            "role": "customer",
            "email": registered_customer["email"],
            "password": "definitely-wrong",
        },
    )
    no_such_account = await client.post(
        "/api/auth/login",
        json={
            "role": "customer",
            "email": "nobody@test.com",
            "password": "definitely-wrong",
        },
    )

    assert wrong_password.status_code == no_such_account.status_code == 401
    assert wrong_password.json()["detail"] == no_such_account.json()["detail"]


# ---------------------------------------------------------------------------
# 5. security 模組的單元測試
# ---------------------------------------------------------------------------


def test_decode_token_對缺少必要_claim_的_token_拋錯() -> None:
    incomplete = _forge({"sub": "1", "role": "customer", "typ": "access"})

    with pytest.raises(TokenError):
        decode_token(incomplete, TokenType.ACCESS)


def test_decode_token_對非數字的_sub_拋錯() -> None:
    bad_sub = _forge(_base_claims(sub="not-a-number"))

    with pytest.raises(TokenError):
        decode_token(bad_sub, TokenType.ACCESS)


def test_正式環境不接受過低的_bcrypt_成本因子() -> None:
    """測試環境調低 bcrypt rounds 是常見做法，但設定被複製到正式環境時
    密碼雜湊會變得可暴力破解，且從外部完全看不出來。讓它在啟動時就失敗。
    """
    from app.core.config import Settings

    common = {
        "_env_file": None,
        "SECRET_KEY": "a" * 40,
        "JWT_SECRET_KEY": "b" * 40,
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/d",
        "REDIS_URL": "redis://localhost:6379/0",
        "BCRYPT_ROUNDS": 4,
    }

    assert Settings(**common, ENVIRONMENT="testing").BCRYPT_ROUNDS == 4

    with pytest.raises(ValidationError):
        Settings(**common, ENVIRONMENT="production")
