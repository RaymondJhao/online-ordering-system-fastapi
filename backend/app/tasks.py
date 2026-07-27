"""背景排程任務。

商業邏輯說明 -『自動釋出未付款庫存』：
顧客下單後，訂單狀態會先是 'New'，代表商家已經知道要準備哪些餐點；
如果顧客遲遲不去完成綠界付款，這筆訂單就會一直卡在 'New'，等同於幫顧客
「預留」了這些餐點的庫存/備料資源，但實際上這筆訂單很可能已經被放棄。
如果沒有機制清掉這種棄單，庫存會被無意義地卡住，導致其他顧客明明看得到
菜單，卻買不到已經被「假裝要買」的餐點。

因此這裡用 APScheduler 開一個背景排程，每分鐘檢查一次：只要訂單建立超過
15 分鐘還沒有付款完成（仍是 'New' 狀態），就視為棄單，自動轉成
'Cancelled'，把庫存釋放回去，讓系統維持正常運作。
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .extensions import db
from .models import Order, OrderStatus

logger = logging.getLogger(__name__)

# 逾時未付款的判定門檻：訂單建立超過這個分鐘數還是 New 狀態，就視為棄單。
UNPAID_ORDER_TIMEOUT_MINUTES = 15


def cancel_unpaid_orders(app):
    """找出所有狀態仍是 'New'、但建立時間已經超過 15 分鐘的訂單，
    代表顧客下單後遲遲沒有完成綠界付款，直接視為棄單並自動取消，
    藉此釋放被這些訂單佔用的餐點庫存，讓其他顧客可以正常下單。

    這個函式會被 BackgroundScheduler 放在獨立的執行緒裡呼叫，
    Flask-SQLAlchemy 的 db.session 必須在 app context 內才能運作，
    所以整段查詢／更新都要包在 `with app.app_context():` 裡面。
    """
    with app.app_context():
        cutoff_time = datetime.now(timezone.utc) - timedelta(
            minutes=UNPAID_ORDER_TIMEOUT_MINUTES
        )

        try:
            # 只挑「還沒付款（New）」且「建立時間早於 15 分鐘前」的訂單，
            # 已經在處理中、已完成、已取消的訂單都不受影響。
            expired_orders = Order.query.filter(
                Order.status == OrderStatus.NEW,
                Order.created_at < cutoff_time,
            ).all()

            if not expired_orders:
                return

            for order in expired_orders:
                order.status = OrderStatus.CANCELLED

            db.session.commit()

            logger.info(
                "已自動取消 %d 筆逾時未付款訂單，釋出對應庫存：%s",
                len(expired_orders),
                [order.id for order in expired_orders],
            )
        except Exception:
            # 任何一步出錯都整批 rollback，避免訂單狀態被改到一半就卡住。
            db.session.rollback()
            logger.exception("自動取消逾時未付款訂單時發生錯誤，已執行 rollback")


def init_scheduler(app):
    """在 Flask app 啟動時呼叫一次：建立 BackgroundScheduler，
    註冊「每分鐘執行一次 cancel_unpaid_orders()」的排程並啟動。
    """
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        func=lambda: cancel_unpaid_orders(app),
        trigger="interval",
        minutes=1,
        id="cancel_unpaid_orders",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
