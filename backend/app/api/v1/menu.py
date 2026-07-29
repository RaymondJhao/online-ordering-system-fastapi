"""菜單與庫存端點。

權限需求從函式內文移到函式簽章：舊版每個路由開頭都有一行
`if get_jwt().get("role") != "merchant": return jsonify(...), 403`，
現在改由 `Depends(require_role("merchant"))` 表達，會一併反映在 OpenAPI 文件上。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, TokenPayloadDep, require_role
from app.core.security import TokenPayload
from app.schemas.menu import MenuItemCreate, MenuItemResponse, MenuItemUpdate
from app.services import menu_service
from app.services.menu_service import MenuItemNotFoundError, NotOwnerError

router = APIRouter(prefix="/menu", tags=["Menu"])

MerchantOnly = Annotated[TokenPayload, Depends(require_role("merchant"))]


@router.get("", response_model=list[MenuItemResponse], summary="瀏覽菜單（公開）")
async def list_menu(db: DbSession) -> list[MenuItemResponse]:
    """顧客可見的菜單，只包含上架且供應中的餐點。此端點不需要登入。"""
    items = await menu_service.list_public_menu(db)
    return [MenuItemResponse.model_validate(item) for item in items]


@router.post(
    "",
    response_model=MenuItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增餐點（限商家）",
)
async def create_menu_item(
    payload: MenuItemCreate, db: DbSession, token: MerchantOnly
) -> MenuItemResponse:
    item = await menu_service.create_menu_item(db, merchant_id=token.subject, payload=payload)
    return MenuItemResponse.model_validate(item)


@router.put("/{item_id}", response_model=MenuItemResponse, summary="更新餐點（限商家）")
async def update_menu_item(
    item_id: int, payload: MenuItemUpdate, db: DbSession, token: MerchantOnly
) -> MenuItemResponse:
    """部分更新。傳入空的 body 時，切換該餐點的上下架狀態（沿用舊版行為）。"""
    try:
        item = await menu_service.update_menu_item(
            db, merchant_id=token.subject, item_id=item_id, payload=payload
        )
    except MenuItemNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotOwnerError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return MenuItemResponse.model_validate(item)


inventory_router = APIRouter(prefix="/inventory", tags=["Inventory"])


@inventory_router.get("", response_model=list[MenuItemResponse], summary="商家庫存清單（限商家）")
async def list_inventory(db: DbSession, token: TokenPayloadDep) -> list[MenuItemResponse]:
    """商家自己的完整品項清單，含已下架者。"""
    if token.role != "merchant":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="此操作僅限 merchant 使用")

    items = await menu_service.list_merchant_inventory(db, token.subject)
    return [MenuItemResponse.model_validate(item) for item in items]
