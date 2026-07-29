from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, jwt_required

from ..extensions import db
from ..models import Customer, Merchant, TokenBlocklist

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

ROLE_MODELS = {
    "customer": Customer,
    "merchant": Merchant,
}


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    role = data.get("role")
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if role not in ROLE_MODELS:
        return jsonify({"message": "role 必須為 'customer' 或 'merchant'"}), 400
    if not name or not email or not password:
        return jsonify({"message": "缺少必要欄位：name、email、password"}), 400

    model = ROLE_MODELS[role]

    if model.query.filter_by(email=email).first() is not None:
        return jsonify({"message": "此信箱已被註冊"}), 400

    if role == "customer":
        user = Customer(name=name, email=email, phone=data.get("phone"))
    else:
        user = Merchant(
            name=name,
            email=email,
            phone=data.get("phone"),
            address=data.get("address"),
        )

    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return (
        jsonify(
            {
                "message": "註冊成功",
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "role": role,
                },
            }
        ),
        201,
    )


@auth_bp.route("/login", methods=["POST"])
def login():
    """使用者登入
    ---
    tags:
      - Auth
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - role
            - email
            - password
          properties:
            role:
              type: string
              enum: [customer, merchant]
              example: customer
            email:
              type: string
              example: customer@test.com
            password:
              type: string
              example: password123
    responses:
      200:
        description: 登入成功，回傳 JWT access_token
        schema:
          type: object
          properties:
            message:
              type: string
              example: 登入成功
            access_token:
              type: string
            user:
              type: object
              properties:
                id:
                  type: integer
                name:
                  type: string
                email:
                  type: string
                role:
                  type: string
      400:
        description: 缺少必要欄位，或 role 不是 customer/merchant
      401:
        description: 信箱或密碼錯誤
    """
    data = request.get_json(silent=True) or {}

    role = data.get("role")
    email = data.get("email")
    password = data.get("password")

    if role not in ROLE_MODELS:
        return jsonify({"message": "role 必須為 'customer' 或 'merchant'"}), 400
    if not email or not password:
        return jsonify({"message": "缺少必要欄位：email、password"}), 400

    model = ROLE_MODELS[role]
    user = model.query.filter_by(email=email).first()

    if user is None or not user.check_password(password):
        return jsonify({"message": "信箱或密碼錯誤"}), 401

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"user_id": user.id, "role": role},
    )

    return (
        jsonify(
            {
                "message": "登入成功",
                "access_token": access_token,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "role": role,
                },
            }
        ),
        200,
    )


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """登出，將目前的 Token 加入 Blocklist 使其立即失效
    ---
    tags:
      - Auth
    security:
      - Bearer: []
    responses:
      200:
        description: 登出成功
    """
    jti = get_jwt()["jti"]

    db.session.add(TokenBlocklist(jti=jti))
    db.session.commit()

    return jsonify({"message": "登出成功"}), 200
