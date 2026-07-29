import os

import redis
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy


def _resolve_ratelimit_storage_uri():
    """實際嘗試連線 Redis，連不到才 fallback 回 in-memory storage，
    避免 Redis 容器沒起來時整個 app 啟動失敗。"""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        redis.from_url(redis_url, socket_connect_timeout=1).ping()
        return redis_url
    except redis.exceptions.RedisError:
        return "memory://"


db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address, storage_uri=_resolve_ratelimit_storage_uri())


@jwt.token_in_blocklist_loader
def check_if_token_in_blocklist(jwt_header, jwt_payload):
    # 延遲匯入避免 models.py（會 import 本檔的 db）與本檔互相循環匯入
    from .models import TokenBlocklist

    jti = jwt_payload["jti"]
    return db.session.query(TokenBlocklist.id).filter_by(jti=jti).first() is not None
