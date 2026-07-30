"""金流端點。"""

from typing import Annotated, Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.api.deps import DbSession, require_role
from app.core.rate_limit import RateLimiter
from app.core.security import TokenPayload
from app.services import payment_service
from app.services.payment_service import (
    NotOwnerError,
    OrderNotFoundError,
    OrderNotPayableError,
)

router = APIRouter(prefix="/payment", tags=["Payment"])

CustomerOnly = Annotated[TokenPayload, Depends(require_role("customer"))]


@router.post(
    "/checkout/{order_id}",
    summary="建立綠界付款（限顧客）",
    # 沿用舊版的 3 per minute。反覆建立付款單除了浪費資源，
    # 也可能被用來對金流商產生大量無效交易。
    dependencies=[Depends(RateLimiter(times=3, seconds=60, scope="checkout"))],
)
async def checkout(order_id: int, db: DbSession, token: CustomerOnly) -> dict[str, Any]:
    """回傳前端送往綠界所需的表單參數與目標網址。"""
    try:
        params = await payment_service.build_checkout_params(
            db, customer_id=token.subject, order_id=order_id
        )
    except OrderNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotOwnerError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OrderNotPayableError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"payment_url": payment_service.ECPAY_CHECKOUT_URL, "form_data": params}


@router.post(
    "/callback",
    response_class=PlainTextResponse,
    summary="綠界付款結果通知（由綠界伺服器呼叫）",
    include_in_schema=False,
)
async def ecpay_callback(request: Request, db: DbSession) -> PlainTextResponse:
    """綠界 ReturnURL。

    三點與一般端點不同：

    1. 沒有登入者，身分驗證改用 CheckMacValue
    2. 請求是 form-encoded 而非 JSON
    3. 回應必須是純文字 "1|OK"／"0|Error"，不是 JSON。
       回傳 JSON 會讓綠界判定通知失敗並持續重送。

    **不要改用 `await request.form()`。** 綠界的 Content-Type 沒有帶 charset，
    Starlette 於是以 Latin-1 解碼 body，中文欄位會變成 mojibake：`RtnMsg`
    的「交易成功」會解成 'äº¤æ\\x98\\x93æ\\x88\\x90å\\x8a\\x9f'。我們接著用 UTF-8
    重新編碼去算 CheckMacValue，算的就是亂碼的雜湊，簽章永遠對不上。

    這個 bug 在正式部署前完全隱形：單元測試自己組的 payload 是 ASCII，
    不會觸發；而線上的症狀只是「簽章不符」，看不出跟編碼有關。

    `keep_blank_values=True` 同樣不可省。綠界會回傳空值欄位
    （CustomField2~4、StoreID），而它們**要參與 CheckMacValue 計算**；
    parse_qsl 預設會把空值丟掉，少了它們簽章一樣算不對。
    """
    raw_body = await request.body()
    form_data = dict(parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True))

    accepted = await payment_service.handle_callback(db, form_data)
    return PlainTextResponse("1|OK" if accepted else "0|Error")
