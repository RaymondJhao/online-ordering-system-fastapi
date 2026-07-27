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
    from .routes.order import order_bp
    from .routes.payment import payment_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(payment_bp)

    return app
