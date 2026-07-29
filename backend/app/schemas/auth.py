"""認證相關的請求與回應 schema。

這些 Pydantic model 同時扮演三個角色：輸入驗證、回應序列化、OpenAPI 文件來源。

對照舊版：`routes/auth.py` 的 login 端點有 60 行手寫 YAML docstring 供 flasgger
產生文件，另有十餘行 `if not x: return 400` 做驗證，兩者各自獨立、容易不同步
（文件寫 required 但程式沒擋是很常見的漂移）。本檔案取代兩者，且永遠一致。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["customer", "merchant"]

# bcrypt 只處理前 72 個位元組。security.py 已用 SHA-256 預先壓縮以支援任意長度，
# 這裡仍設上限純粹是為了擋下超大 payload 造成的資源浪費。
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "customer",
                "name": "王小明",
                "email": "customer@example.com",
                "password": "password123",
                "phone": "0912345678",
            }
        }
    )

    role: Role
    name: Annotated[str, Field(min_length=1, max_length=100)]
    email: EmailStr
    password: PasswordStr
    phone: Annotated[str | None, Field(default=None, max_length=20)]
    address: Annotated[str | None, Field(default=None, max_length=255)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "customer",
                "email": "customer@example.com",
                "password": "password123",
            }
        }
    )

    role: Role
    email: EmailStr
    password: PasswordStr


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    """回應中的使用者資訊。

    刻意不包含 password_hash——`from_attributes` 只會取出這裡宣告的欄位，
    因此不會有「不小心把整個 ORM 物件序列化出去」的風險。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    phone: str | None = None


class UserWithRoleResponse(UserResponse):
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    # S105 會把 token_type 誤判為硬編密碼；這是 OAuth2 規範的欄位名，值固定為 "bearer"
    token_type: Literal["bearer"] = "bearer"  # noqa: S105


class LoginResponse(TokenResponse):
    user: UserWithRoleResponse


class MessageResponse(BaseModel):
    message: str
