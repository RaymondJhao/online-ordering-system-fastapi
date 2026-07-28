"""
pytest 共用設定與 fixtures。

極度重要：測試一律使用記憶體內的 SQLite (`sqlite:///:memory:`)，
不可連到 .env 裡設定的開發用 MySQL，避免測試不小心污染/清空真實資料。
"""

import os
import sys
from decimal import Decimal

import pytest

# tests/ 目錄底下沒有 __init__.py，pytest 預設只會把 tests/ 本身加進 sys.path，
# 不會把上層的 backend/ 加進去；這裡手動補上，確保不論從哪個目錄執行
# `pytest`，都能正確 `import app`。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import Coupon, Customer, DiscountType, MenuItem, Merchant  # noqa: E402


class TestConfig(Config):
    """測試專用設定。"""

    TESTING = True
    # create_app() 內：`if not app.debug or WERKZEUG_RUN_MAIN == "true":` 才會啟動
    # APScheduler 背景排程。測試環境沒有透過 werkzeug reloader 執行，
    # 把 DEBUG 設成 True 可以讓這個條件為 False，避免背景排程在測試時被意外啟動，
    # 跟著去操作/鎖住我們的記憶體測試資料庫。
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    JWT_SECRET_KEY = "test-jwt-secret-key-with-enough-entropy-for-hs256"
    # 關閉 Flask-Limiter 速率限制，避免測試案例互相干擾（例如同一分鐘內
    # 重複呼叫下單 API 時，被 5 per minute 的限制擋下來）。
    RATELIMIT_ENABLED = False


@pytest.fixture()
def app():
    """建立一個乾淨的 Flask app，資料庫為記憶體內 SQLite，測試結束即銷毀。"""
    application = create_app(TestConfig)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    """Flask 測試用 HTTP client。"""
    return app.test_client()


@pytest.fixture()
def runner(app):
    """Flask CLI 測試用 runner。"""
    return app.test_cli_runner()


@pytest.fixture()
def init_db(app):
    """預先塞入基礎假資料：一個商家、一個顧客、一個餐點、一張優惠券。"""
    merchant = Merchant(
        name="測試商家",
        email="merchant@test.com",
        phone="0900000000",
        address="測試市測試路 1 號",
    )
    merchant.set_password("password123")

    customer = Customer(
        name="測試顧客",
        email="customer@test.com",
        phone="0911111111",
    )
    customer.set_password("password123")

    _db.session.add_all([merchant, customer])
    _db.session.flush()  # 先取得 merchant.id，後面建立餐點/優惠券才有外鍵可用

    menu_item = MenuItem(
        merchant_id=merchant.id,
        name="招牌漢堡",
        price=Decimal("120.00"),
        description="測試用品項",
        stock=50,
    )
    coupon = Coupon(
        code="OPEN888",
        discount_type=DiscountType.FIXED,
        discount_value=50,
        merchant_id=merchant.id,
        is_active=True,
    )

    _db.session.add_all([menu_item, coupon])
    _db.session.commit()

    return {
        "merchant": merchant,
        "customer": customer,
        "menu_item": menu_item,
        "coupon": coupon,
    }


def _login(client, role, email, password="password123"):
    """呼叫 /api/auth/login 取得 JWT access token。"""
    response = client.post(
        "/api/auth/login",
        json={"role": role, "email": email, "password": password},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["access_token"]


@pytest.fixture()
def merchant_token(client, init_db):
    """已登入商家的 JWT access token。"""
    return _login(client, "merchant", init_db["merchant"].email)


@pytest.fixture()
def customer_token(client, init_db):
    """已登入顧客的 JWT access token。"""
    return _login(client, "customer", init_db["customer"].email)
