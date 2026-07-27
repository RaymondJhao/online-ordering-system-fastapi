from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from ..extensions import db, limiter
from ..models import MenuItem, Merchant, Order, OrderItem, OrderStatus, PaymentMethod

order_bp = Blueprint("order", __name__, url_prefix="/api/orders")

VALID_STATUSES = {status.value for status in OrderStatus}
VALID_PAYMENT_METHODS = {method.value for method in PaymentMethod}

# 嚴格狀態轉移表：key 為目前狀態，value 為允許轉入的下一個狀態集合。
# 不在此表中的轉移一律視為非法（含「轉回自己」與任何跳躍式轉移）。
ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: {OrderStatus.REFUNDED},
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}


def serialize_order(order):
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "merchant_id": order.merchant_id,
        "status": order.status.value,
        "payment_status": order.payment_status.value,
        "payment_method": order.payment_method.value,
        "reject_reason": order.reject_reason,
        "total_price": float(order.total_price),
        "pickup_time": order.pickup_time.isoformat() if order.pickup_time else None,
        "table_number": order.table_number,
        "created_at": order.created_at.isoformat(),
        "items": [
            {
                "menu_item_id": item.menu_item_id,
                "name": item.menu_item.name,
                "quantity": item.quantity,
                "price": float(item.price),
            }
            for item in order.order_items
        ],
    }


@order_bp.route("", methods=["POST"])
@limiter.limit("5 per minute")
@jwt_required()
def create_order():
    if get_jwt().get("role") != "customer":
        return jsonify({"message": "僅限顧客下單"}), 403

    customer_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    merchant_id = data.get("merchant_id")
    items = data.get("items")

    if not merchant_id or not isinstance(items, list) or len(items) == 0:
        return (
            jsonify({"message": "缺少必要欄位：merchant_id、items（且 items 不可為空陣列）"}),
            400,
        )

    try:
        merchant_id = int(merchant_id)
    except (TypeError, ValueError):
        return jsonify({"message": "merchant_id 格式錯誤"}), 400

    if Merchant.query.get(merchant_id) is None:
        return jsonify({"message": "商家不存在"}), 404

    payment_method = data.get("payment_method", PaymentMethod.ONLINE.value)
    if payment_method not in VALID_PAYMENT_METHODS:
        return (
            jsonify(
                {"message": f"payment_method 必須為以下其中之一：{sorted(VALID_PAYMENT_METHODS)}"}
            ),
            400,
        )

    # 驗證每個品項的格式與數量，並收集要查詢的 menu_item_id
    parsed_items = []
    for raw_item in items:
        if not isinstance(raw_item, dict) or "menu_item_id" not in raw_item or "quantity" not in raw_item:
            return jsonify({"message": "items 陣列中每個項目需包含 menu_item_id 與 quantity"}), 400

        try:
            menu_item_id = int(raw_item["menu_item_id"])
            quantity = int(raw_item["quantity"])
        except (TypeError, ValueError):
            return jsonify({"message": "menu_item_id 與 quantity 必須為整數"}), 400

        if quantity <= 0:
            return jsonify({"message": "quantity 必須為正整數"}), 400

        parsed_items.append((menu_item_id, quantity))

    menu_item_ids = [menu_item_id for menu_item_id, _ in parsed_items]
    menu_items = MenuItem.query.filter(
        MenuItem.id.in_(menu_item_ids), MenuItem.merchant_id == merchant_id
    ).all()
    menu_item_map = {menu_item.id: menu_item for menu_item in menu_items}

    if len(menu_item_map) != len(set(menu_item_ids)):
        return jsonify({"message": "部分餐點不存在，或不屬於指定的商家"}), 400

    # 由後端依資料庫單價計算總價，避免前端價格造假；Order 與所有 OrderItem
    # 於同一個 session/transaction 內寫入，任何一步失敗都會整筆 rollback。
    try:
        total_price = 0
        order = Order(
            customer_id=customer_id,
            merchant_id=merchant_id,
            total_price=0,
            status=OrderStatus.PENDING,
            payment_method=PaymentMethod(payment_method),
            table_number=data.get("table_number"),
        )

        for menu_item_id, quantity in parsed_items:
            menu_item = menu_item_map[menu_item_id]
            unit_price = menu_item.price
            total_price += unit_price * quantity
            order.order_items.append(
                OrderItem(menu_item_id=menu_item.id, quantity=quantity, price=unit_price)
            )

        order.total_price = total_price

        db.session.add(order)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "訂單建立失敗，請稍後再試"}), 500

    return jsonify({"message": "訂單建立成功", "order": serialize_order(order)}), 201


@order_bp.route("", methods=["GET"])
@jwt_required()
def list_orders():
    claims = get_jwt()
    role = claims.get("role")
    user_id = int(get_jwt_identity())

    if role == "customer":
        orders = (
            Order.query.filter_by(customer_id=user_id)
            .order_by(Order.created_at.desc())
            .all()
        )
    elif role == "merchant":
        orders = (
            Order.query.filter_by(merchant_id=user_id)
            .order_by(Order.created_at.desc())
            .all()
        )
    else:
        return jsonify({"message": "無效的角色"}), 403

    return jsonify({"orders": [serialize_order(order) for order in orders]}), 200


@order_bp.route("/<int:order_id>/status", methods=["PUT"])
@jwt_required()
def update_order_status(order_id):
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    order = Order.query.get(order_id)

    if order is None:
        return jsonify({"message": "訂單不存在"}), 404
    if order.merchant_id != merchant_id:
        return jsonify({"message": "無權操作此訂單"}), 403

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")

    if new_status not in VALID_STATUSES:
        return (
            jsonify({"message": f"status 必須為以下其中之一：{sorted(VALID_STATUSES)}"}),
            400,
        )

    target_status = OrderStatus(new_status)

    if target_status == OrderStatus.REJECTED:
        reject_reason = data.get("reject_reason")
        if not reject_reason or not str(reject_reason).strip():
            return jsonify({"message": "拒絕訂單時必須提供 reject_reason"}), 400

    if target_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        return (
            jsonify(
                {
                    "message": f"無法將訂單狀態從 {order.status.value} 轉換為 {target_status.value}"
                }
            ),
            409,
        )

    if target_status == OrderStatus.REJECTED:
        order.reject_reason = str(data.get("reject_reason")).strip()

    order.status = target_status
    db.session.commit()

    return jsonify({"message": "訂單狀態已更新", "order": serialize_order(order)}), 200
