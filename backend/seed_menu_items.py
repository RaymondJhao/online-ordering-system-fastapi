"""一次性測試資料腳本：幫指定商家塞幾筆 MenuItem，方便在 Postman 測試下單 API。
用法：python seed_menu_items.py <merchant_email>
測試完可以直接刪除這個檔案，不屬於正式功能。
"""

import sys

from app import create_app
from app.extensions import db
from app.models import Coupon, DiscountType, Merchant, MenuItem

if len(sys.argv) != 2:
    raise SystemExit("用法：python seed_menu_items.py <merchant_email>")

merchant_email = sys.argv[1]

app = create_app()
with app.app_context():
    merchant = Merchant.query.filter_by(email=merchant_email).first()
    if merchant is None:
        raise SystemExit(f"找不到 email={merchant_email} 的商家，請先用 Postman 註冊一個 merchant 帳號")

    items = [
        MenuItem(merchant_id=merchant.id, name="招牌漢堡", price=120, description="測試用品項", stock=50),
        MenuItem(merchant_id=merchant.id, name="薯條", price=60, description="測試用品項", stock=50),
    ]
    db.session.add_all(items)
    db.session.commit()

    print(f"已為商家 {merchant.name}（id={merchant.id}）新增以下 MenuItem：")
    for item in items:
        print(f"  id={item.id}  name={item.name}  price={item.price}  stock={item.stock}")

    # code 欄位是全域唯一，重複執行這支腳本時直接略過，避免撞 IntegrityError
    coupon = Coupon.query.filter_by(code="OPEN888").first()
    if coupon is None:
        coupon = Coupon(
            code="OPEN888",
            discount_type=DiscountType.FIXED,
            discount_value=50,
            merchant_id=merchant.id,
            is_active=True,
        )
        db.session.add(coupon)
        db.session.commit()
        print(f"已新增測試優惠券：code={coupon.code}  discount_type={coupon.discount_type.value}  discount_value={coupon.discount_value}")
    else:
        print(f"測試優惠券 code={coupon.code} 已存在，略過建立")
