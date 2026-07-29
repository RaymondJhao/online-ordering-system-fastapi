"""優惠券的商業邏輯。"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Coupon, DiscountType
from app.schemas.coupon import CouponCreate


class DuplicateCouponCodeError(Exception):
    pass


class CouponNotApplicableError(Exception):
    """優惠碼不存在、已停用，或不屬於這個商家。"""


async def create_coupon(db: AsyncSession, *, merchant_id: int, payload: CouponCreate) -> Coupon:
    coupon = Coupon(
        code=payload.code.strip(),
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        is_active=payload.is_active,
        merchant_id=merchant_id,
    )
    db.add(coupon)
    try:
        await db.commit()
    except IntegrityError as exc:
        # code 有 unique 約束。用「先查再寫」無法避免併發下的重複，
        # 交給資料庫約束把關才是可靠的做法。
        await db.rollback()
        raise DuplicateCouponCodeError("此優惠碼已存在") from exc
    return coupon


async def list_merchant_coupons(db: AsyncSession, merchant_id: int) -> list[Coupon]:
    result = await db.execute(
        select(Coupon).where(Coupon.merchant_id == merchant_id).order_by(Coupon.id)
    )
    return list(result.scalars().all())


async def resolve_coupon(db: AsyncSession, *, code: str | None, merchant_id: int) -> Coupon | None:
    """把優惠碼換成 Coupon 物件；未提供優惠碼時回傳 None。"""
    if not code:
        return None

    result = await db.execute(
        select(Coupon).where(
            Coupon.code == code,
            Coupon.merchant_id == merchant_id,
            Coupon.is_active.is_(True),
        )
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise CouponNotApplicableError("優惠碼不存在、已停用，或不適用於此商家")
    return coupon


def calculate_discount(total_price: Decimal, coupon: Coupon | None) -> int:
    """計算折扣金額。

    折扣不可超過原始總價，否則會出現負數的訂單金額——這在金流串接上
    會直接被擋下，或更糟：算成負數的請款金額。
    """
    if coupon is None:
        return 0

    if coupon.discount_type is DiscountType.PERCENTAGE:
        discount = int(total_price * coupon.discount_value / 100)
    else:
        discount = coupon.discount_value

    return max(0, min(discount, int(total_price)))
