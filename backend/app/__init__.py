from flask import Flask

from .config import Config
from .extensions import bcrypt, db, jwt


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)

    from . import models  # noqa: F401  (registers models with SQLAlchemy)
    from .routes.auth import auth_bp
    from .routes.order import order_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(order_bp)

    return app
