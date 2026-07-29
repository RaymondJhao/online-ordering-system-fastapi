"""API v1 路由匯總。

對照舊版 `create_app()` 裡的七個 `app.register_blueprint(...)`。
"""

from fastapi import APIRouter

from app.api.v1 import auth, coupon, menu, order, payment

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(menu.router)
api_router.include_router(menu.inventory_router)
api_router.include_router(coupon.router)
api_router.include_router(order.router)
api_router.include_router(order.merchant_router)
api_router.include_router(payment.router)
