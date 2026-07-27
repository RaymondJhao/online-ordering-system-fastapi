from flask import Blueprint, jsonify

from ..models import MenuItem

menu_bp = Blueprint("menu", __name__, url_prefix="/api/menu")


def serialize_menu_item(item):
    return {
        "id": item.id,
        "merchant_id": item.merchant_id,
        "name": item.name,
        "price": float(item.price),
        "description": item.description,
        "is_available": item.is_available,
    }


@menu_bp.route("/", methods=["GET"], strict_slashes=False)
def list_menu_items():
    items = MenuItem.query.filter_by(is_available=True).all()
    return jsonify([serialize_menu_item(item) for item in items]), 200
