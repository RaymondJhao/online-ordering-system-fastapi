import os
import time
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from ..extensions import db
from ..models import Order, OrderStatus
from ..utils.ecpay import generate_check_mac_value

payment_bp = Blueprint("payment", __name__, url_prefix="/api/payment")

ECPAY_MERCHANT_ID = os.environ.get("ECPAY_MERCHANT_ID", "2000132")
ECPAY_CHECKOUT_URL = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"
ECPAY_RETURN_URL = os.environ.get(
    "ECPAY_RETURN_URL",
    "https://your-ngrok-domain.ngrok-free.app/api/payment/ecpay/callback",
)


@payment_bp.route("/checkout/<int:order_id>", methods=["POST"])
@jwt_required()
def checkout(order_id):
    if get_jwt().get("role") != "customer":
        return jsonify({"message": "僅限顧客付款"}), 403

    customer_id = int(get_jwt_identity())
    order = Order.query.get(order_id)

    if order is None:
        return jsonify({"message": "訂單不存在"}), 404
    if order.customer_id != customer_id:
        return jsonify({"message": "無權操作此訂單"}), 403
    if order.status != OrderStatus.NEW:
        return jsonify({"message": "此訂單目前狀態無法建立付款"}), 400

    merchant_trade_no = f"ORD{order.id}{int(time.time())}"

    params = {
        "MerchantID": ECPAY_MERCHANT_ID,
        "MerchantTradeNo": merchant_trade_no,
        "MerchantTradeDate": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio",
        "TotalAmount": int(round(float(order.total_price))),
        "TradeDesc": "線上點餐訂單",
        "ItemName": "線上餐點",
        "ReturnURL": ECPAY_RETURN_URL,
        "ChoosePayment": "Credit",
        "EncryptType": 1,
        # 綠界會原封不動把 CustomField1~4 傳回 ReturnURL callback，用它來可靠地帶回 order_id，
        # 不要依賴解析 MerchantTradeNo（id 跟 timestamp 中間沒有分隔符，解析回去會有歧義）。
        "CustomField1": str(order.id),
    }
    params["CheckMacValue"] = generate_check_mac_value(params)

    return jsonify({"payment_url": ECPAY_CHECKOUT_URL, "form_data": params}), 200


@payment_bp.route("/callback", methods=["POST"])
def ecpay_callback():
    """綠界 ReturnURL：綠界的背景伺服器直接呼叫，沒有登入者、不能用 JWT 驗證身分。
    改用 CheckMacValue 驗證這筆通知確實來自綠界、且內容未被竄改。"""
    data = request.form.to_dict()

    received_mac = data.pop("CheckMacValue", None)
    expected_mac = generate_check_mac_value(data)

    if not received_mac or received_mac != expected_mac:
        return "0|Error"

    if data.get("RtnCode") == "1":
        order_id = data.get("CustomField1")
        order = Order.query.get(int(order_id)) if order_id and order_id.isdigit() else None

        if order is not None and order.status == OrderStatus.NEW:
            try:
                order.status = OrderStatus.PROCESSING
                db.session.commit()
            except Exception:
                db.session.rollback()
                return "0|Error"

    return "1|OK"
