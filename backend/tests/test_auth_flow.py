"""認證端點的正常流程與輸入驗證。"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Merchant


async def test_註冊顧客成功(client: AsyncClient, db: AsyncSession) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "王小明",
            "email": "new-customer@test.com",
            "password": "password123",
            "phone": "0912345678",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-customer@test.com"
    assert body["role"] == "customer"
    assert "password" not in body
    assert "password_hash" not in body

    stored = await db.scalar(select(Customer).where(Customer.email == "new-customer@test.com"))
    assert stored is not None
    assert stored.password_hash != "password123"


async def test_註冊商家成功(client: AsyncClient, db: AsyncSession) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "merchant",
            "name": "測試餐廳",
            "email": "new-merchant@test.com",
            "password": "password123",
            "address": "台北市測試路 1 號",
        },
    )

    assert response.status_code == 201
    assert response.json()["role"] == "merchant"
    assert await db.scalar(select(Merchant).where(Merchant.email == "new-merchant@test.com"))


async def test_重複信箱註冊回_409(client: AsyncClient, registered_customer) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "另一個人",
            "email": registered_customer["email"],
            "password": "password123",
        },
    )
    assert response.status_code == 409


async def test_無效的_role_回_422(client: AsyncClient) -> None:
    """Pydantic 的 Literal 型別直接擋下，不需要在路由裡手寫檢查。

    對照舊版：`if role not in ROLE_MODELS: return jsonify(...), 400`。
    """
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "admin",
            "name": "壞人",
            "email": "bad@test.com",
            "password": "password123",
        },
    )
    assert response.status_code == 422


async def test_信箱格式錯誤回_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "格式錯誤",
            "email": "not-an-email",
            "password": "password123",
        },
    )
    assert response.status_code == 422


async def test_密碼過短回_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "密碼太短",
            "email": "short@test.com",
            "password": "1234",
        },
    )
    assert response.status_code == 422


async def test_登入回傳_token_與使用者資訊(client: AsyncClient, registered_customer) -> None:
    response = await client.post(
        "/api/auth/login",
        json={
            "role": "customer",
            "email": registered_customer["email"],
            "password": registered_customer["password"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["email"] == registered_customer["email"]
    assert body["user"]["role"] == "customer"


async def test_以錯誤角色登入會失敗(client: AsyncClient, registered_customer) -> None:
    """同一個信箱在 customer 與 merchant 是不同的帳號。"""
    response = await client.post(
        "/api/auth/login",
        json={
            "role": "merchant",
            "email": registered_customer["email"],
            "password": registered_customer["password"],
        },
    )
    assert response.status_code == 401


async def test_OAuth2_表單端點可供_Swagger_使用(client: AsyncClient, registered_customer) -> None:
    """/token 接受 form-encoded，email 填在 OAuth2 規範的 username 欄位。"""
    response = await client.post(
        "/api/auth/token",
        data={
            "username": registered_customer["email"],
            "password": registered_customer["password"],
        },
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


async def test_me_回傳目前登入者(client: AsyncClient, logged_in_customer) -> None:
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {logged_in_customer['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == logged_in_customer["user"]["email"]


async def test_openapi_文件包含_security_scheme(client: AsyncClient) -> None:
    """驗證 OpenAPI 文件由型別註記自動產生，且 Authorize 按鈕可運作。

    舊版需要在 run.py 手寫 securityDefinitions，並在每個路由的 docstring
    重複寫 `security: - Bearer: []`。
    """
    spec = (await client.get("/openapi.json")).json()

    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
    assert spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]["type"] == "oauth2"
    assert "/api/auth/me" in spec["paths"]
    assert "security" in spec["paths"]["/api/auth/me"]["get"]
