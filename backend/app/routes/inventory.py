from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from ..models import MenuItem

inventory_bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")


@inventory_bp.route("", methods=["GET"])
@jwt_required()
def list_inventory():
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    items = MenuItem.query.filter_by(merchant_id=merchant_id).all()

    return (
        jsonify(
            {
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "price": float(item.price),
                        "stock": item.stock,
                        "is_active": item.is_active,
                    }
                    for item in items
                ]
            }
        ),
        200,
    )
