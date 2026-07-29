"""優惠券端點。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, require_role
from app.core.security import TokenPayload
from app.schemas.coupon import CouponCreate, CouponResponse
from app.services import coupon_service
from app.services.coupon_service import DuplicateCouponCodeError

router = APIRouter(prefix="/coupons", tags=["Coupon"])

MerchantOnly = Annotated[TokenPayload, Depends(require_role("merchant"))]


@router.post(
    "",
    response_model=CouponResponse,
    status_code=status.HTTP_201_CREATED,
    summary="建立優惠券（限商家）",
)
async def create_coupon(
    payload: CouponCreate, db: DbSession, token: MerchantOnly
) -> CouponResponse:
    try:
        coupon = await coupon_service.create_coupon(db, merchant_id=token.subject, payload=payload)
    except DuplicateCouponCodeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return CouponResponse.model_validate(coupon)


@router.get("", response_model=list[CouponResponse], summary="優惠券清單（限商家）")
async def list_coupons(db: DbSession, token: MerchantOnly) -> list[CouponResponse]:
    coupons = await coupon_service.list_merchant_coupons(db, token.subject)
    return [CouponResponse.model_validate(coupon) for coupon in coupons]
