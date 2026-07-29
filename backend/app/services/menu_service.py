"""餐點與庫存的商業邏輯。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MenuItem
from app.schemas.menu import MenuItemCreate, MenuItemUpdate


class MenuItemNotFoundError(Exception):
    pass


class NotOwnerError(Exception):
    """操作的餐點不屬於這個商家。"""


async def list_public_menu(db: AsyncSession) -> list[MenuItem]:
    """顧客可見的菜單：只包含上架且供應中的餐點。"""
    result = await db.execute(
        select(MenuItem)
        .where(MenuItem.is_available.is_(True), MenuItem.is_active.is_(True))
        .order_by(MenuItem.id)
    )
    return list(result.scalars().all())


async def list_merchant_inventory(db: AsyncSession, merchant_id: int) -> list[MenuItem]:
    """商家自己的完整品項清單，含已下架者。"""
    result = await db.execute(
        select(MenuItem).where(MenuItem.merchant_id == merchant_id).order_by(MenuItem.id)
    )
    return list(result.scalars().all())


async def create_menu_item(
    db: AsyncSession, *, merchant_id: int, payload: MenuItemCreate
) -> MenuItem:
    menu_item = MenuItem(
        merchant_id=merchant_id,
        name=payload.name.strip(),
        price=payload.price,
        description=payload.description.strip() if payload.description else None,
        stock=payload.stock,
    )
    db.add(menu_item)
    await db.commit()
    return menu_item


async def _get_owned_menu_item(db: AsyncSession, *, merchant_id: int, item_id: int) -> MenuItem:
    menu_item = await db.get(MenuItem, item_id)
    if menu_item is None:
        raise MenuItemNotFoundError("餐點不存在")
    if menu_item.merchant_id != merchant_id:
        raise NotOwnerError("無權操作此餐點")
    return menu_item


async def update_menu_item(
    db: AsyncSession, *, merchant_id: int, item_id: int, payload: MenuItemUpdate
) -> MenuItem:
    """部分更新。

    `exclude_unset=True` 只取出請求中實際帶了的欄位，因此可以精確區分
    「沒有要改這個欄位」與「要把它改成 null」。舊版靠 `if "name" in data`
    手動達成同樣效果。

    另外保留舊版的一個行為：body 完全為空時，切換上下架狀態。
    這是既有前端在用的介面，遷移階段不改變契約。
    """
    menu_item = await _get_owned_menu_item(db, merchant_id=merchant_id, item_id=item_id)

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        menu_item.is_active = not menu_item.is_active
    else:
        for field, value in updates.items():
            if field in {"name", "description"} and isinstance(value, str):
                value = value.strip() or None
            setattr(menu_item, field, value)

    await db.commit()
    return menu_item
