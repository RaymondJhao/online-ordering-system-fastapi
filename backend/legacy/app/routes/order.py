from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..extensions import db, limiter
from ..models import (
    Coupon,
    DiscountType,
    IdempotencyRecord,
    MenuItem,
    Merchant,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
)

order_bp = Blueprint("order", __name__, url_prefix="/api/orders")
merchant_order_bp = Blueprint("merchant_order", __name__, url_prefix="/api/merchant")

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


def _parse_pickup_time(raw_pickup_time):
    """回傳 (pickup_time, error_response)；未提供時回傳 (None, None)。"""
    if not raw_pickup_time:
        return None, None
    try:
        pickup_time = datetime.fromisoformat(str(raw_pickup_time).replace("Z", "+00:00"))
    except ValueError:
        return None, (jsonify({"message": "pickup_time 格式錯誤，請使用 ISO 8601 格式"}), 400)

    # 防呆：pickup_time 不可為過去時間。輸入可能是 naive 或 aware datetime，
    # 比較時要用同一種時區基準，否則 naive/aware 混比會直接丟 TypeError。
    now = datetime.now(pickup_time.tzinfo) if pickup_time.tzinfo else datetime.now()
    if pickup_time < now:
        return None, (jsonify({"message": "pickup_time 不可為過去時間"}), 400)

    return pickup_time, None


def _resolve_coupon(coupon_code, merchant_id):
    """回傳 (coupon, error_response)；未提供優惠碼時回傳 (None, None)。"""
    if not coupon_code:
        return None, None
    coupon = Coupon.query.filter_by(
        code=coupon_code, merchant_id=merchant_id, is_active=True
    ).first()
    if coupon is None:
        return None, (jsonify({"message": "優惠碼不存在、已停用，或不適用於此商家"}), 400)
    return coupon, None


def _parse_items(items):
    """驗證 items 陣列格式，回傳 (parsed_items, error_response)。
    parsed_items 是 [(menu_item_id, quantity), ...]。"""
    parsed_items = []
    for raw_item in items:
        if not isinstance(raw_item, dict) or "menu_item_id" not in raw_item or "quantity" not in raw_item:
            return None, (jsonify({"message": "items 陣列中每個項目需包含 menu_item_id 與 quantity"}), 400)

        try:
            menu_item_id = int(raw_item["menu_item_id"])
            quantity = int(raw_item["quantity"])
        except (TypeError, ValueError):
            return None, (jsonify({"message": "menu_item_id 與 quantity 必須為整數"}), 400)

        if quantity <= 0:
            return None, (jsonify({"message": "quantity 必須為正整數"}), 400)

        parsed_items.append((menu_item_id, quantity))

    return parsed_items, None


def _load_menu_items(parsed_items, merchant_id):
    """依 merchant_id 撈出對應餐點，回傳 (menu_item_map, error_response)。"""
    menu_item_ids = [menu_item_id for menu_item_id, _ in parsed_items]
    menu_items = MenuItem.query.filter(
        MenuItem.id.in_(menu_item_ids), MenuItem.merchant_id == merchant_id
    ).all()
    menu_item_map = {menu_item.id: menu_item for menu_item in menu_items}

    if len(menu_item_map) != len(set(menu_item_ids)):
        return None, (jsonify({"message": "部分餐點不存在，或不屬於指定的商家"}), 400)

    return menu_item_map, None


def _deduct_stock(parsed_items):
    """原子扣庫存：不能先 SELECT 讀庫存再判斷再 UPDATE，兩個請求之間有空隙，
    高併發下會超賣（race condition）。改用單一 SQL 語句，把「檢查庫存足夠」
    跟「扣庫存」在資料庫層級合成同一個原子操作：WHERE 條件同時卡數量與 id，
    若該列因為 stock 不足而沒被 WHERE 卡到，rowcount 就會是 0。
    成功回傳 None，庫存不足時回傳 error_response。"""
    for menu_item_id, quantity in parsed_items:
        result = db.session.execute(
            text(
                "UPDATE menu_items SET stock = stock - :quantity "
                "WHERE id = :id AND stock >= :quantity"
            ),
            {"quantity": quantity, "id": menu_item_id},
        )
        if result.rowcount == 0:
            db.session.rollback()
            return (
                jsonify(
                    {
                        "message": f"餐點庫存不足，訂單建立失敗（menu_item_id={menu_item_id}）"
                    }
                ),
                400,
            )
    return None


def _apply_coupon_discount(total_price, coupon, order):
    """依優惠券折抵，折扣金額不可超過購物車原始總價（避免出現負的訂單金額）。
    回傳最終 discount_amount，並直接寫入 order.coupon_id。"""
    discount_amount = 0
    if coupon is not None:
        if coupon.discount_type == DiscountType.PERCENTAGE:
            discount_amount = int(total_price * coupon.discount_value / 100)
        else:
            discount_amount = coupon.discount_value
        discount_amount = max(0, min(discount_amount, int(total_price)))
        order.coupon_id = coupon.id
    return discount_amount


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
        "coupon_id": order.coupon_id,
        "discount_amount": order.discount_amount,
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
    """顧客建立訂單
    ---
    tags:
      - Orders
    security:
      - Bearer: []
    parameters:
      - in: header
        name: Idempotency-Key
        type: string
        required: false
        description: 冪等性金鑰；重送相同的 key 不會重複建單或重複扣庫存
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - merchant_id
            - items
          properties:
            merchant_id:
              type: integer
              example: 1
            items:
              type: array
              items:
                type: object
                properties:
                  menu_item_id:
                    type: integer
                  quantity:
                    type: integer
              example:
                - menu_item_id: 1
                  quantity: 2
            payment_method:
              type: string
              enum: [online, cash]
              example: online
            coupon_code:
              type: string
              example: OPEN888
            pickup_time:
              type: string
              example: "2026-07-29T18:30:00"
            table_number:
              type: string
              example: "A5"
    responses:
      201:
        description: 訂單建立成功
      400:
        description: 缺少必要欄位、格式錯誤，或餐點庫存不足
      403:
        description: 僅限顧客下單（role 必須為 customer）
      404:
        description: 商家不存在
    """
    if get_jwt().get("role") != "customer":
        return jsonify({"message": "僅限顧客下單"}), 403

    # 冪等性防護：客戶端在網路逾時／雙擊送出等情況下可能用同一把 Idempotency-Key
    # 重送同一筆下單請求。若這把 key 先前已經處理過，直接回傳當初存下的回應，
    # 絕對不要重複扣庫存或重複建單。
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        existing_record = IdempotencyRecord.query.filter_by(key=idempotency_key).first()
        if existing_record is not None:
            return jsonify(existing_record.response_body), 200

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

    if db.session.get(Merchant, merchant_id) is None:
        return jsonify({"message": "商家不存在"}), 404

    payment_method = data.get("payment_method", PaymentMethod.ONLINE.value)
    if payment_method not in VALID_PAYMENT_METHODS:
        return (
            jsonify(
                {"message": f"payment_method 必須為以下其中之一：{sorted(VALID_PAYMENT_METHODS)}"}
            ),
            400,
        )

    pickup_time, error_response = _parse_pickup_time(data.get("pickup_time"))
    if error_response:
        return error_response

    coupon, error_response = _resolve_coupon(data.get("coupon_code"), merchant_id)
    if error_response:
        return error_response

    parsed_items, error_response = _parse_items(items)
    if error_response:
        return error_response

    menu_item_map, error_response = _load_menu_items(parsed_items, merchant_id)
    if error_response:
        return error_response

    # 由後端依資料庫單價計算總價，避免前端價格造假；Order、所有 OrderItem、
    # 庫存扣減與 IdempotencyRecord 都在同一個 session/transaction 內寫入，
    # 任何一步失敗都會整筆 rollback。
    try:
        total_price = 0
        order = Order(
            customer_id=customer_id,
            merchant_id=merchant_id,
            total_price=0,
            status=OrderStatus.PENDING,
            payment_method=PaymentMethod(payment_method),
            table_number=data.get("table_number"),
            pickup_time=pickup_time,
        )

        for menu_item_id, quantity in parsed_items:
            menu_item = menu_item_map[menu_item_id]
            unit_price = menu_item.price
            total_price += unit_price * quantity
            order.order_items.append(
                OrderItem(menu_item_id=menu_item.id, quantity=quantity, price=unit_price)
            )

        discount_amount = _apply_coupon_discount(total_price, coupon, order)
        order.discount_amount = discount_amount
        order.total_price = total_price - discount_amount

        stock_error_response = _deduct_stock(parsed_items)
        if stock_error_response:
            return stock_error_response

        db.session.add(order)
        db.session.flush()  # 取得 order.id，讓存進 IdempotencyRecord 的回應內容是完整的

        response_body = {"message": "訂單建立成功", "order": serialize_order(order)}

        if idempotency_key:
            db.session.add(
                IdempotencyRecord(key=idempotency_key, response_body=response_body)
            )

        db.session.commit()
    except IntegrityError:
        # 極端併發情況：兩個帶著相同 Idempotency-Key 的請求同時通過了前面的
        # 「查無記錄」檢查，此時 unique key 的資料庫約束會讓後 commit 的那個
        # 請求在這裡失敗；rollback 掉它自己（含庫存扣減），改回傳先寫入成功
        # 那筆請求的回應，確保不會重複扣庫存或重複建單。
        db.session.rollback()
        if idempotency_key:
            existing_record = IdempotencyRecord.query.filter_by(key=idempotency_key).first()
            if existing_record is not None:
                return jsonify(existing_record.response_body), 200
        return jsonify({"message": "訂單建立失敗，請稍後再試"}), 500
    except Exception:
        db.session.rollback()
        return jsonify({"message": "訂單建立失敗，請稍後再試"}), 500

    return jsonify(response_body), 201


@merchant_order_bp.route("/orders", methods=["POST"])
@jwt_required()
def create_merchant_order():
    """商家在大螢幕手動建立現場／電話訂單：沒有顧客帳號，customer_id 一律為 null，
    merchant_id 直接取自登入商家的身分，不必（也不能）由前端指定。"""
    if get_jwt().get("role") != "merchant":
        return jsonify({"message": "僅限商家操作"}), 403

    merchant_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"message": "缺少必要欄位：items（且不可為空陣列）"}), 400

    payment_method = data.get("payment_method", PaymentMethod.CASH.value)
    if payment_method not in VALID_PAYMENT_METHODS:
        return (
            jsonify(
                {"message": f"payment_method 必須為以下其中之一：{sorted(VALID_PAYMENT_METHODS)}"}
            ),
            400,
        )

    pickup_time, error_response = _parse_pickup_time(data.get("pickup_time"))
    if error_response:
        return error_response

    coupon, error_response = _resolve_coupon(data.get("coupon_code"), merchant_id)
    if error_response:
        return error_response

    parsed_items, error_response = _parse_items(items)
    if error_response:
        return error_response

    menu_item_map, error_response = _load_menu_items(parsed_items, merchant_id)
    if error_response:
        return error_response

    # 與顧客下單相同：Order、所有 OrderItem、庫存扣減都在同一個 session/transaction
    # 內寫入，任何一步失敗都會整筆 rollback。
    try:
        total_price = 0
        order = Order(
            customer_id=None,
            merchant_id=merchant_id,
            total_price=0,
            status=OrderStatus.PENDING,
            payment_method=PaymentMethod(payment_method),
            table_number=data.get("table_number"),
            pickup_time=pickup_time,
        )

        for menu_item_id, quantity in parsed_items:
            menu_item = menu_item_map[menu_item_id]
            unit_price = menu_item.price
            total_price += unit_price * quantity
            order.order_items.append(
                OrderItem(menu_item_id=menu_item.id, quantity=quantity, price=unit_price)
            )

        discount_amount = _apply_coupon_discount(total_price, coupon, order)
        order.discount_amount = discount_amount
        order.total_price = total_price - discount_amount

        stock_error_response = _deduct_stock(parsed_items)
        if stock_error_response:
            return stock_error_response

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
    order = db.session.get(Order, order_id)

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
