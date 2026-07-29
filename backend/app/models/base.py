"""所有 ORM model 的共用基底。"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, Numeric
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase

# 統一約束命名規則。SQLAlchemy 預設不會替 unique / check / foreign key 產生名稱，
# 交由資料庫自動命名；不同資料庫產生的名稱不同，Alembic 之後想要 drop 某個約束時
# 就會因為找不到名稱而失敗。先訂好規則，所有 migration 的命名才是可預期的。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """帶時區的現在時間。

    舊版同樣使用 aware datetime，但欄位定義是 `db.Column(db.DateTime)`（無時區），
    寫進資料庫時時區資訊會被丟棄，讀回來變成 naive datetime。
    `tasks.py` 拿它與 aware 的 cutoff_time 比較，在 Postgres 上會直接拋 TypeError。
    本版所有 datetime 欄位都是 TIMESTAMP WITH TIME ZONE，見 Base.type_annotation_map。
    """
    return datetime.now(UTC)


class Base(AsyncAttrs, DeclarativeBase):
    """ORM 基底類別。

    繼承 AsyncAttrs 之後，未載入的關聯可以用 `await obj.awaitable_attrs.orders`
    顯式載入，作為忘記 eager load 時的逃生口。但正常情況仍應在查詢時就用
    selectinload / joinedload 指定，避免 N+1。
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # 讓 `Mapped[Decimal]` 與 `Mapped[datetime]` 自動對應到正確的資料庫型別，
    # 不必在每個 mapped_column 重複寫 Numeric(10, 2) / DateTime(timezone=True)。
    type_annotation_map = {  # noqa: RUF012
        Decimal: Numeric(10, 2),
        datetime: DateTime(timezone=True),
    }

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"
