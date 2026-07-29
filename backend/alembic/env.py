"""Alembic 環境設定（async 版）。

舊專案沒有任何遷移工具，schema 靠 `db.create_all()` 建立。那個做法在開發初期
很方便，但一旦資料表已經有正式資料就無法再變更結構——create_all 只會建立
不存在的表，不會處理欄位新增、型別變更或索引調整。

這裡改用 Alembic，並支援兩種模式：
- online：實際連線資料庫執行遷移
- offline：只輸出 SQL（`alembic upgrade head --sql`），供 DBA 審核或
  在無法直連正式資料庫的環境中套用
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的比對基準。app.models 的 __init__ 已匯入所有 model，
# 因此這份 metadata 是完整的。
target_metadata = Base.metadata


def get_database_url() -> str:
    """從應用程式設定取得連線字串，而非寫死在 alembic.ini。"""
    return get_settings().database_url_str


def _configure_common(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        # 預設不會偵測欄位型別的變更（例如 String(50) 改成 String(100)），
        # 開啟後 autogenerate 才會產生對應的 alter。
        compare_type=True,
        # 同理，預設也不會偵測 server_default 的變更。
        compare_server_default=True,
        # 讓約束名稱遵循 models/base.py 的 NAMING_CONVENTION
        render_as_batch=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure_common(
        url=get_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure_common(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
