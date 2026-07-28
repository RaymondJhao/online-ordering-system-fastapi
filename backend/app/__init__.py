import os

from flask import Flask, jsonify

from .config import Config
from .extensions import bcrypt, db, jwt, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)

    @app.errorhandler(429)
    def handle_rate_limit_exceeded(error):
        return (
            jsonify({"message": f"請求過於頻繁，請稍後再試（限制：{error.description}）"}),
            429,
        )

    from . import models  # noqa: F401  (registers models with SQLAlchemy)
    from .routes.auth import auth_bp
    from .routes.coupon import coupon_bp
    from .routes.inventory import inventory_bp
    from .routes.menu import menu_bp
    from .routes.order import merchant_order_bp, order_bp
    from .routes.payment import payment_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(coupon_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(menu_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(merchant_order_bp)
    app.register_blueprint(payment_bp)

    # Flask 開發模式(debug=True)預設會啟用 reloader，實際上會啟動「監控」跟「工作」
    # 兩個process；如果不加這層判斷，背景排程會被啟動兩次。WERKZEUG_RUN_MAIN 只有在
    # 真正執行程式邏輯的那個 process 裡才會是 "true"，藉此確保排程只會啟動一次。
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from .tasks import init_scheduler

        app.scheduler = init_scheduler(app)

    return app
