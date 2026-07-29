"""健康檢查端點。"""

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_健康檢查在資料庫正常時回傳_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


async def test_openapi_文件可正常產生() -> None:
    """驗證 FastAPI 能從型別註記產生 OpenAPI 3.1 文件。

    舊版需要在每個路由手寫 YAML docstring 給 flasgger，兩者容易不同步；
    這裡的文件直接來自函式簽章，不會漂移。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["openapi"].startswith("3.1")
    assert "/health" in spec["paths"]
