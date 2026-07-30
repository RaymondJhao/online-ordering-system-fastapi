"""健康檢查端點與部署相關的設定。"""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app

# ---------------------------------------------------------------------------
# liveness / readiness
# ---------------------------------------------------------------------------


async def test_liveness_不需要資料庫也能回應() -> None:
    """/health/live 必須完全不碰相依服務。

    Render 會定期打 healthCheckPath；若該端點在資料庫不通時回 503，
    平台會判定實例不健康而反覆重啟。本專案用的免費 PostgreSQL 每 30 天
    到期需要重建，那段空窗期最不需要的就是重啟迴圈。

    這個測試刻意不使用 client fixture（不覆寫 get_db），
    藉此證明這條路徑真的沒有資料庫依賴。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_會檢查資料庫與_redis(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"


async def test_health_是_readiness_的別名(client: AsyncClient) -> None:
    """保留 /health 讓既有的監控設定不會壞掉。"""
    assert (await client.get("/health")).json() == (await client.get("/health/ready")).json()


async def test_openapi_文件可正常產生(client: AsyncClient) -> None:
    """驗證 FastAPI 能從型別註記產生 OpenAPI 3.1 文件。

    舊版需要在每個路由手寫 YAML docstring 給 flasgger，兩者容易不同步；
    這裡的文件直接來自函式簽章，不會漂移。
    """
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["openapi"].startswith("3.1")
    assert "/health/live" in spec["paths"]
    assert "/health/ready" in spec["paths"]


# ---------------------------------------------------------------------------
# 連線字串正規化
# ---------------------------------------------------------------------------


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        SECRET_KEY="a" * 40,
        JWT_SECRET_KEY="b" * 40,
        REDIS_URL="redis://localhost:6379/0",
        DATABASE_URL=database_url,
    )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Render 的 Internal Database URL
        (
            "postgresql://u:p@dpg-abc/db",
            "postgresql+asyncpg://u:p@dpg-abc/db",
        ),
        # Render 的 External URL 會附上 sslmode
        (
            "postgresql://u:p@dpg-abc.oregon-postgres.render.com/db?sslmode=require",
            "postgresql+asyncpg://u:p@dpg-abc.oregon-postgres.render.com/db?ssl=require",
        ),
        # Heroku 沿用至今的舊 scheme
        (
            "postgres://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # Neon 還會多帶一個 asyncpg 不認得的 channel_binding
        (
            "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.neon.tech/neondb?ssl=require",
        ),
        # 已經是 async driver 就原樣保留
        (
            "postgresql+asyncpg://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # 明確關閉 SSL 時不要硬加回去
        (
            "postgresql://u:p@host/db?sslmode=disable",
            "postgresql+asyncpg://u:p@host/db",
        ),
    ],
)
def test_雲端平台的連線字串會被正規化(given: str, expected: str) -> None:
    """平台注入的字串應該可以直接複製貼上使用。

    兩個常見的失敗都會產生誤導性的錯誤訊息：
    - 同步 driver → "The asyncio extension requires an async driver"
    - sslmode / channel_binding → asyncpg 直接拒絕未知參數

    兩者看起來都像「連線字串填錯」，部署當下很難判斷真正的原因。
    """
    assert _settings(given).database_url_str == expected


def test_正式環境不接受過低的_bcrypt_成本因子() -> None:
    """測試環境調低 bcrypt rounds 是常見做法，但設定被複製到正式環境時
    密碼雜湊會變得可暴力破解，且從外部完全看不出來。讓它在啟動時就失敗。
    """
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


# ---------------------------------------------------------------------------
# 未處理例外的回應
# ---------------------------------------------------------------------------


async def test_未處理例外的500回應必須帶上CORS_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """500 回應少了 CORS header，前端就看不到真正的錯誤。

    Starlette 的 `ServerErrorMiddleware` 在使用者中介層**之外**，所以未處理
    例外產生的 500 不會經過 `CORSMiddleware`。瀏覽器擋掉之後，axios 拿不到
    response，`extractErrorMessage()` 只能回報「無法連線到伺服器」——
    所有伺服器錯誤都被誤報成網路問題，把人指向完全錯誤的方向。

    修正的關鍵**只在中介層的註冊順序**：攔截器要先註冊（因此在內層），
    CORS 後註冊（因此在外層），回應才會在往外走時被補上 header。
    順序寫反等於沒改，而且從測試以外的地方看不出差別——所以需要這個測試。

    注意 `@app.exception_handler(Exception)` 解決不了這件事：FastAPI 會把
    Exception 的處理器交給 ServerErrorMiddleware，位置仍在 CORS 之外。
    """
    from app.services import menu_service

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("刻意觸發未處理的例外")

    monkeypatch.setattr(menu_service, "list_public_menu", _boom)

    origin = "http://localhost:5173"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/menu", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.json() == {"detail": "伺服器內部錯誤"}
    assert response.headers.get("access-control-allow-origin") == origin, (
        "500 回應少了 CORS header，前端會把伺服器錯誤誤判成網路問題"
    )
