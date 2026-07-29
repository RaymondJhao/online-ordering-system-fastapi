"""冪等性記錄。

客戶端在網路逾時重試、或使用者連點兩次送出時，可能用同一把 Idempotency-Key
送出兩筆相同的下單請求。這張表記錄已處理過的 key 與當時的回應內容，
第二次請求直接回放原本的結果，不會重複扣庫存、重複建單。

為什麼留在 Postgres 而不像 JWT blocklist 一樣搬去 Redis：
這裡需要的是「唯一約束 + 與訂單寫入落在同一個交易」的保證。key 的插入必須
與建立訂單同進同退，Redis 做不到跨系統的原子性。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
