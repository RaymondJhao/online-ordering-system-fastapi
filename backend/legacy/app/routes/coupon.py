from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Coupon, DiscountType

coupon_bp = Blueprint("coupon", __name__, url_prefix="/api/coupons")

VALID_DISCOUNT_TYPES = {discount_type.value for discount_type in DiscountType}


def serialize_coupon(coupon):
    return {
        "id": coupon.id,
        "code": coupon.code,
        "discount_type": coupon.discount_type.value,
        "discount_value": coupon.discount_value,
        "is_active": coupon.is_active,
        "merchant_id": coupon.merchant_id,
    }


@coupon_bp.route("", methods=["POST"])
@jwt_required()
def create_coupon():
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    code = data.get("code")
    discount_type = data.get("discount_type")
    discount_value = data.get("discount_value")
    is_active = data.get("is_active", True)

    if not code or not str(code).strip():
        return jsonify({"message": "缺少必要欄位：code"}), 400
    if discount_type not in VALID_DISCOUNT_TYPES:
        return (
            jsonify(
                {"message": f"discount_type 必須為以下其中之一：{sorted(VALID_DISCOUNT_TYPES)}"}
            ),
            400,
        )

    try:
        discount_value = int(discount_value)
    except (TypeError, ValueError):
        return jsonify({"message": "discount_value 必須為整數"}), 400

    if discount_value <= 0:
        return jsonify({"message": "discount_value 必須為正整數"}), 400
    if discount_type == DiscountType.PERCENTAGE.value and discount_value > 100:
        return jsonify({"message": "discount_type 為 PERCENTAGE 時，discount_value 不可超過 100"}), 400
    if not isinstance(is_active, bool):
        return jsonify({"message": "is_active 必須為布林值"}), 400

    coupon = Coupon(
        code=str(code).strip(),
        discount_type=DiscountType(discount_type),
        discount_value=discount_value,
        is_active=is_active,
        merchant_id=merchant_id,
    )

    try:
        db.session.add(coupon)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "此優惠碼已存在"}), 400

    return jsonify({"message": "優惠券建立成功", "coupon": serialize_coupon(coupon)}), 201


@coupon_bp.route("", methods=["GET"])
@jwt_required()
def list_coupons():
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    coupons = Coupon.query.filter_by(merchant_id=merchant_id).all()

    return jsonify({"coupons": [serialize_coupon(coupon) for coupon in coupons]}), 200
