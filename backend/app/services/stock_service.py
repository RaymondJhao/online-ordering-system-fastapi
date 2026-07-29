"""庫存扣減。

整個專案最需要正確的一段邏輯，因此單獨成一個模組並附上完整說明。
"""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MenuItem


class InsufficientStockError(Exception):
    def __init__(self, menu_item_id: int) -> None:
        self.menu_item_id = menu_item_id
        super().__init__(f"餐點庫存不足，訂單建立失敗（menu_item_id={menu_item_id}）")


def _deduct_statement(menu_item_id: int, quantity: int):
    """「檢查庫存足夠」與「扣減庫存」必須是同一個原子操作。

    錯誤的寫法（先讀再判斷再寫）::

        item = await db.get(MenuItem, id)
        if item.stock >= qty:      # ← 這兩行之間，另一個請求可能讀到同樣的庫存
            item.stock -= qty      #    兩者都通過檢查，結果賣超

    正確的寫法是把條件放進 UPDATE 的 WHERE 子句，由資料庫在單一語句內完成
    「找到庫存足夠的那一列並扣減」。庫存不足時 WHERE 不成立，沒有任何一列
    被更新，rowcount 即為 0。

    這個做法不需要顯式鎖，也不需要提高交易隔離級別——UPDATE 本身會對命中的
    資料列加上行鎖，併發請求排隊執行，後到者看到的是已扣減後的庫存。

    `synchronize_session="fetch"` 是必要的：這是一個繞過 ORM 的批次 UPDATE，
    沒有它，session 裡既有的 MenuItem 物件仍保留舊的 stock 值，
    同一個 session 之後讀到的會是過期資料（本專案的 expire_on_commit=False
    讓這個問題更明顯，因為 commit 也不會讓屬性失效）。
    """
    return (
        update(MenuItem)
        .where(MenuItem.id == menu_item_id, MenuItem.stock >= quantity)
        .values(stock=MenuItem.stock - quantity)
        .execution_options(synchronize_session="fetch")
    )


async def deduct_stock(db: AsyncSession, items: list[tuple[int, int]]) -> None:
    """依序扣減多個品項的庫存，任一品項不足即拋出例外。

    呼叫端負責 rollback：庫存扣減與訂單寫入必須落在同一筆交易，
    只扣了庫存卻沒建立訂單、或反之，都會造成資料不一致。

    品項先依 id 排序再扣，是為了避免死結：兩筆訂單若同時包含 A、B 兩個品項
    而加鎖順序相反，會互相等待對方持有的行鎖。固定順序即可消除循環等待。
    """
    for menu_item_id, quantity in sorted(items):
        result = await db.execute(_deduct_statement(menu_item_id, quantity))
        if result.rowcount == 0:
            raise InsufficientStockError(menu_item_id)


async def restore_stock(db: AsyncSession, items: list[tuple[int, int]]) -> None:
    """把庫存加回去，供訂單被拒絕、取消或退款時使用。"""
    for menu_item_id, quantity in sorted(items):
        await db.execute(
            update(MenuItem)
            .where(MenuItem.id == menu_item_id)
            .values(stock=MenuItem.stock + quantity)
            .execution_options(synchronize_session="fetch")
        )
