"""訂單相關的列舉型別。

沿用舊版的 values_callable 設定，讓資料庫存的是 "PENDING" 這樣的值而非
成員名稱，兩者在此剛好相同，但寫明可避免日後改動成員名稱時破壞既有資料。

型別選擇說明：這裡使用 Postgres 原生 ENUM。優點是資料庫層即保證值的正確性；
代價是新增狀態需要 ALTER TYPE，Alembic 也需要手動處理。若日後訂單狀態變動頻繁，
可改為 VARCHAR + CHECK 約束，遷移成本較低。
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    ONLINE = "ONLINE"


class DiscountType(StrEnum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """建立具名的 Postgres ENUM 型別。

    一定要指定 name：沒有名稱時 Alembic autogenerate 產生的 migration
    會出現隨機或重複的型別名稱，導致遷移無法重現。
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
    )
