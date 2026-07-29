"""
註冊 / 登入相關 API 的 pytest 整合測試。

涵蓋四個情境：
1. 成功註冊新顧客，且資料庫內儲存的是雜湊過的密碼（不可為明文）。
2. 使用已存在的 email 重複註冊，應回傳 400。
3. 使用正確帳密登入，應回傳 200 並帶有 access_token。
4. 使用錯誤密碼登入，應回傳 401。
"""

from app.models import Customer


def test_register_customer_success_and_password_is_hashed(client):
    """成功註冊新顧客：回傳 201，且資料庫裡存的密碼是 bcrypt 雜湊值，不是明文。"""
    response = client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "新顧客",
            "email": "new_customer@test.com",
            "password": "plain-password-123",
            "phone": "0922222222",
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["user"]["email"] == "new_customer@test.com"

    # 從資料庫撈出剛註冊的顧客，確認密碼欄位已被雜湊加密
    customer = Customer.query.filter_by(email="new_customer@test.com").first()
    assert customer is not None
    assert customer.password_hash != "plain-password-123"  # 不可為明文
    assert customer.check_password("plain-password-123")  # 雜湊值仍可正確驗證原密碼


def test_register_fails_with_duplicate_email(client, init_db):
    """使用已被註冊過的 email 再次註冊，應回傳 400，且不能建立第二筆帳號。"""
    existing_email = init_db["customer"].email  # init_db 已預先建立 customer@test.com

    response = client.post(
        "/api/auth/register",
        json={
            "role": "customer",
            "name": "重複的顧客",
            "email": existing_email,
            "password": "another-password",
        },
    )

    assert response.status_code == 400

    # 資料庫裡該 email 仍然只有一筆帳號
    assert Customer.query.filter_by(email=existing_email).count() == 1


def test_login_success_returns_access_token(client, init_db):
    """使用正確帳密登入，應回傳 200 並在回應內容中帶有 access_token。"""
    response = client.post(
        "/api/auth/login",
        json={
            "role": "customer",
            "email": init_db["customer"].email,
            "password": "password123",  # 與 conftest.py init_db 建立顧客時設定的密碼一致
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "access_token" in body
    assert body["access_token"]  # token 不可為空字串


def test_login_fails_with_wrong_password(client, init_db):
    """使用錯誤密碼登入，應回傳 401 Unauthorized。"""
    response = client.post(
        "/api/auth/login",
        json={
            "role": "customer",
            "email": init_db["customer"].email,
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
