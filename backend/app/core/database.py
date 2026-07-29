"""Async 資料庫連線與 Session 管理。

取代舊版 Flask-SQLAlchemy 的全域 `db` 物件（`app/extensions.py`）。

三個關鍵差異：

1. **沒有全域 session**。舊版的 `db.session` 是綁在 Flask request context 上的
   全域代理物件，任何地方 import 就能用。這裡改為由 `get_db()` 依賴注入
   AsyncSession，session 的生命週期與請求一致且顯式可見。

2. **expire_on_commit=False**（見下方註解）。這是 async SQLAlchemy 最容易踩的坑。

3. **交易邊界由 service 層決定**。`get_db()` 只負責建立與釋放 session，
   以及在例外發生時 rollback；commit 的時機交給 service 層自行決定，
   避免舊版那種在 helper 函式中途 rollback、難以追蹤的寫法。
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Environment, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """建立（並快取）async engine。

    刻意不在模組載入時就建立，理由與 config 相同：讓本模組可以被安全 import，
    測試才能在不連資料庫的情況下 import models。
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url_str,
        # pool_pre_ping 會在借出連線前送一個輕量查詢，確認連線仍然有效。
        # 免費方案的資料庫常會主動斷開閒置連線，沒有這個設定會在半夜排程
        # 或流量低谷後的第一個請求拿到已失效的連線。
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        echo=settings.ENVIRONMENT is Environment.DEVELOPMENT,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        # expire_on_commit 預設為 True：commit 後所有 ORM 物件的屬性會被標記為
        # 過期，下次存取時自動重新查詢。在同步 SQLAlchemy 這只是多一次 SELECT，
        # 但在 async 下那個「自動重新查詢」是隱式 I/O，會直接拋 MissingGreenlet。
        # 典型症狀：service 裡 commit 之後回傳 order 物件，路由層要序列化
        # order.id 時整個請求爆掉。設為 False 即可避免。
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依賴：提供一個請求範圍的 AsyncSession。

    用法：`async def endpoint(db: Annotated[AsyncSession, Depends(get_db)])`

    這裡不主動 commit。哪些操作要落在同一個交易裡，是商業邏輯的決定，
    應該由 service 層明確表達，而不是由框架在請求結束時默默 commit。
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """關閉連線池，供 lifespan 的 shutdown 階段呼叫。"""
    engine = get_engine()
    await engine.dispose()
