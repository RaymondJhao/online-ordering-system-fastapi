"""ORM models。

Alembic 的 autogenerate 只看得到「已經被 import 過」的 model，
因此這裡必須把所有 model 匯入，讓 Base.metadata 是完整的。

相對舊版 `app/models.py` 的兩處移除：

- `TokenBlocklist`：JWT 撤銷名單改存 Redis（Phase 2）。舊版用資料表儲存，
  但沒有任何清理機制，token 早就過期了紀錄仍留在表裡無限成長。
  Redis 的 TTL 可以讓紀錄在 token 自然失效時一起消失。
- `association_proxy`（`MenuItem.orders` / `Order.menu_items`）：
  確認過整個 routes/ 與 tests/ 都沒有使用。association_proxy 在 async 下
  會觸發隱式 lazy load 而拋 MissingGreenlet，留著只是負債。
  需要跨 OrderItem 查詢時，在 service 層明確寫 join 即可。
"""

from app.models.base import Base
from app.models.coupon import Coupon
from app.models.enums import DiscountType, OrderStatus, PaymentMethod, PaymentStatus
from app.models.idempotency import IdempotencyRecord
from app.models.menu import MenuItem
from app.models.order import Order, OrderItem
from app.models.user import Customer, Merchant

__all__ = [
    "Base",
    "Coupon",
    "Customer",
    "DiscountType",
    "IdempotencyRecord",
    "MenuItem",
    "Merchant",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaymentMethod",
    "PaymentStatus",
]
