from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from ..extensions import db
from ..models import MenuItem

menu_bp = Blueprint("menu", __name__, url_prefix="/api/menu")


def serialize_menu_item(item):
    return {
        "id": item.id,
        "merchant_id": item.merchant_id,
        "name": item.name,
        "price": float(item.price),
        "description": item.description,
        "stock": item.stock,
        "is_available": item.is_available,
        "is_active": item.is_active,
<<<<<<< HEAD
        "stock": item.stock,
=======
>>>>>>> test/backend-pytest
    }


@menu_bp.route("/", methods=["GET"], strict_slashes=False)
def list_menu_items():
    items = MenuItem.query.filter_by(is_available=True, is_active=True).all()
    return jsonify([serialize_menu_item(item) for item in items]), 200


<<<<<<< HEAD
@menu_bp.route("", methods=["POST"])
=======
@menu_bp.route("/", methods=["POST"], strict_slashes=False)
>>>>>>> test/backend-pytest
@jwt_required()
def create_menu_item():
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    name = data.get("name")
<<<<<<< HEAD
    description = data.get("description")
    price = data.get("price")
=======
    price = data.get("price")
    description = data.get("description")
    stock = data.get("stock", 0)
>>>>>>> test/backend-pytest

    if not name or not str(name).strip():
        return jsonify({"message": "缺少必要欄位：name"}), 400

    try:
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({"message": "price 必須為數字"}), 400
<<<<<<< HEAD

    if price <= 0:
        return jsonify({"message": "price 必須為正數"}), 400

    item = MenuItem(
        merchant_id=merchant_id,
        name=str(name).strip(),
        description=str(description).strip() if description else None,
        price=price,
    )

    db.session.add(item)
    db.session.commit()

    return jsonify({"message": "餐點新增成功", "item": serialize_menu_item(item)}), 201
=======
    if price <= 0:
        return jsonify({"message": "price 必須大於 0"}), 400

    try:
        stock = int(stock)
    except (TypeError, ValueError):
        return jsonify({"message": "stock 必須為整數"}), 400
    if stock < 0:
        return jsonify({"message": "stock 不可為負數"}), 400

    menu_item = MenuItem(
        merchant_id=merchant_id,
        name=str(name).strip(),
        price=price,
        description=description,
        stock=stock,
    )

    db.session.add(menu_item)
    db.session.commit()

    return (
        jsonify({"message": "餐點新增成功", "menu_item": serialize_menu_item(menu_item)}),
        201,
    )
>>>>>>> test/backend-pytest


@menu_bp.route("/<int:item_id>", methods=["PUT"])
@jwt_required()
def update_menu_item(item_id):
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
<<<<<<< HEAD
    item = MenuItem.query.filter_by(id=item_id, merchant_id=merchant_id).first()
    if not item:
        return jsonify({"message": "找不到餐點"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = data.get("name")
        if not name or not str(name).strip():
            return jsonify({"message": "name 不可為空"}), 400
        item.name = str(name).strip()

    if "description" in data:
        description = data.get("description")
        item.description = str(description).strip() if description else None

    if "price" in data:
        try:
            price = float(data.get("price"))
        except (TypeError, ValueError):
            return jsonify({"message": "price 必須為數字"}), 400
        if price <= 0:
            return jsonify({"message": "price 必須為正數"}), 400
        item.price = price

    if "is_active" in data:
        is_active = data.get("is_active")
        if not isinstance(is_active, bool):
            return jsonify({"message": "is_active 必須為布林值"}), 400
        item.is_active = is_active

    db.session.commit()

    return jsonify({"message": "餐點更新成功", "item": serialize_menu_item(item)}), 200
=======
    menu_item = db.session.get(MenuItem, item_id)

    if menu_item is None:
        return jsonify({"message": "餐點不存在"}), 404
    if menu_item.merchant_id != merchant_id:
        return jsonify({"message": "無權操作此餐點"}), 403

    data = request.get_json(silent=True) or {}

    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            return jsonify({"message": "is_active 必須為布林值"}), 400
        menu_item.is_active = data["is_active"]
    else:
        # 未指定 is_active 時，預設為切換目前的上下架狀態
        menu_item.is_active = not menu_item.is_active

    db.session.commit()

    return (
        jsonify({"message": "餐點狀態已更新", "menu_item": serialize_menu_item(menu_item)}),
        200,
    )
>>>>>>> test/backend-pytest
