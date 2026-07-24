import os
import time
from datetime import datetime

from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

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
    }
    params["CheckMacValue"] = generate_check_mac_value(params)

    return jsonify({"payment_url": ECPAY_CHECKOUT_URL, "form_data": params}), 200
