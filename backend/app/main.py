"""FastAPI 應用程式進入點。

對應舊版 Flask 的 `app/__init__.py` 的 `create_app()` 與 `run.py`。

兩點值得注意的差異：

1. 舊版用 `WERKZEUG_RUN_MAIN` 環境變數判斷是否為 reloader 的子行程，藉此避免
   背景排程被啟動兩次。FastAPI 改用 `lifespan` 生命週期管理器，啟動與關閉邏輯
   有明確的掛載點，那段 hack 可以直接刪除。

2. 舊版用 flasgger 加上手寫 YAML docstring 產生文件（`routes/auth.py` 的 login
   有 60 行 YAML 只為了描述輸入輸出）。FastAPI 直接從型別註記與 Pydantic model
   產生 OpenAPI 3.1，文件與驗證邏輯永遠同步。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router
from app.core.config import Environment, get_settings
from app.core.database import dispose_engine, get_db
from app.core.redis import close_redis, get_redis
from app.core.scheduler import create_scheduler

# 在此呼叫一次：設定有誤時，應用程式會在啟動階段就失敗，而不是等到第一個請求。
settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """應用程式啟動與關閉時執行的工作。

    資料庫與 Redis 的連線池都採 lazy 建立（第一個請求時才真正連線），
    因此 startup 只需要處理排程；shutdown 則必須顯式關閉所有資源，
    否則行程結束時會留下未關閉的連線與仍在跑的排程執行緒。
    """
    # --- startup ---
    scheduler = None
    if settings.SCHEDULER_ENABLED:
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("背景排程已啟動，間隔 %d 秒", settings.SCHEDULER_INTERVAL_SECONDS)

    yield

    # --- shutdown ---
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="線上點餐系統後端 API（FastAPI + async SQLAlchemy + PostgreSQL）",
    lifespan=lifespan,
    # 正式環境關閉互動式文件，避免對外暴露完整 API 結構
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Vercel 的 preview 部署每次都是隨機子網域（例如
    # online-ordering-abc123-raymond.vercel.app），固定清單比對不到。
    # 用 regex 才能讓 PR 的預覽環境也能呼叫 API。
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health/live", tags=["System"], summary="存活檢查（不檢查相依服務）")
async def liveness() -> dict[str, str]:
    """只回報「這個行程還活著」，不碰資料庫與 Redis。

    為什麼要跟 readiness 分開：Render 會定期打 `healthCheckPath`，若該端點
    在資料庫不通時回 503，平台會判定實例不健康而反覆重啟，甚至讓部署失敗。
    這個專案用的是免費方案的 PostgreSQL，**每 30 天會過期需要重建**（見 README），
    重建的空窗期若讓整個服務進入重啟迴圈，只會讓問題更難排查。

    liveness 的語意是「要不要重啟我」，readiness 才是「能不能把流量給我」。
    資料庫掛掉時正確的行為是回報未就緒，而不是重啟一個沒有問題的行程。

    這個端點也適合當作外部監控的探測目標——它不會喚醒任何相依服務。
    """
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": settings.VERSION}


@app.get("/health/ready", tags=["System"], summary="就緒檢查（含相依服務）")
@app.get("/health", tags=["System"], summary="就緒檢查（/health/ready 的別名）")
async def readiness(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """回報服務與相依元件的狀態。

    任一相依服務不通就回 503：健康檢查若只回報「行程還活著」，
    就無法察覺一個連不到資料庫、每個請求都失敗的實例。
    """
    try:
        await db.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:  # 健康檢查要吞下所有錯誤並回報為不健康，不能讓例外往上拋
        database_status = "unavailable"

    try:
        await get_redis().ping()
        redis_status = "ok"
    except Exception:
        redis_status = "unavailable"

    healthy = database_status == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "database": database_status,
        "redis": redis_status,
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT.value,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.ENVIRONMENT is Environment.DEVELOPMENT,
    )
