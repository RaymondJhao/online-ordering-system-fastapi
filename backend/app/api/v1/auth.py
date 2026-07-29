"""認證端點。

端點設計上刻意保留兩個登入入口：

- `POST /login`   JSON body，維持與既有 React 前端相同的契約，遷移不需改前端
- `POST /token`   form-encoded，OAuth2 password flow 的標準形式，
                  供 Swagger UI 的 Authorize 按鈕使用

兩者共用同一份 service 函式，差別只在輸入格式。這是刻意的取捨：
完全遵循 OAuth2 標準會迫使前端改用 form 並把 email 塞進 username 欄位，
而完全不遵循則會讓 /docs 無法互動測試。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession, TokenPayloadDep, TokenStoreDep
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    Role,
    TokenResponse,
    UserWithRoleResponse,
)
from app.services import auth_service
from app.services.auth_service import AuthError, EmailAlreadyRegisteredError

router = APIRouter(prefix="/auth", tags=["Auth"])


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserWithRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="註冊顧客或商家帳號",
)
async def register(payload: RegisterRequest, db: DbSession) -> UserWithRoleResponse:
    try:
        user = await auth_service.register(
            db,
            role=payload.role,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            phone=payload.phone,
            address=payload.address,
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return UserWithRoleResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=payload.role,
    )


@router.post("/login", response_model=LoginResponse, summary="登入（JSON，供前端使用）")
async def login(payload: LoginRequest, db: DbSession, store: TokenStoreDep) -> LoginResponse:
    try:
        user = await auth_service.authenticate(
            db, role=payload.role, email=payload.email, password=payload.password
        )
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    tokens = await auth_service.issue_token_pair(store, user_id=user.id, role=payload.role)

    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        user=UserWithRoleResponse(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone,
            role=payload.role,
        ),
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="登入（OAuth2 表單，供 Swagger UI 使用）",
)
async def login_for_swagger(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    store: TokenStoreDep,
    role: Role = "customer",
) -> TokenResponse:
    """OAuth2 password flow 的標準端點。

    OAuth2 規範的欄位名是 `username`，本系統以 email 登入，
    因此在 Swagger 的 Authorize 對話框請把 email 填在 username 欄位。
    """
    try:
        user = await auth_service.authenticate(
            db, role=role, email=form_data.username, password=form_data.password
        )
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    tokens = await auth_service.issue_token_pair(store, user_id=user.id, role=role)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenResponse, summary="換發 token（含輪替）")
async def refresh(payload: RefreshRequest, store: TokenStoreDep) -> TokenResponse:
    """用 refresh token 換取新的一組 token。

    每次換發都會輪替：舊的 refresh token 立刻失效。若同一個 refresh token
    被使用第二次，代表它已經外洩，系統會撤銷整條 token family，
    使用者與攻擊者雙方都必須重新登入。
    """
    try:
        tokens = await auth_service.rotate_refresh_token(store, refresh_token=payload.refresh_token)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", response_model=MessageResponse, summary="登出")
async def logout(payload: TokenPayloadDep, store: TokenStoreDep) -> MessageResponse:
    """撤銷目前的 access token 與整條 token family。

    只撤銷 access token 是不夠的：攻擊者若同時持有 refresh token，
    仍可在下一秒換出新的 access token。
    """
    await auth_service.logout(
        store,
        access_jti=payload.jti,
        access_ttl=payload.seconds_until_expiry,
        family_id=payload.family_id or "",
    )
    return MessageResponse(message="登出成功")


@router.get("/me", response_model=UserWithRoleResponse, summary="取得目前登入者資訊")
async def read_current_user(user: CurrentUser, payload: TokenPayloadDep) -> UserWithRoleResponse:
    return UserWithRoleResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=payload.role,  # type: ignore[arg-type]
    )
