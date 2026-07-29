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

# 在此呼叫一次：設定有誤時，應用程式會在啟動階段就失敗，而不是等到第一個請求。
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """應用程式啟動與關閉時執行的工作。

    後續階段會在這裡接上：
      - Phase 4：AsyncIOScheduler 背景排程、fastapi-limiter 初始化

    資料庫與 Redis 的連線池都採 lazy 建立（第一個請求時才真正連線），
    因此 startup 不需要動作；shutdown 則必須顯式關閉，
    否則行程結束時會留下未關閉的連線。
    """
    # --- startup ---
    yield
    # --- shutdown ---
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["System"], summary="健康檢查")
async def health_check(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """回報服務與其相依元件的狀態，供容器編排與 Render 的健康檢查使用。

    資料庫不通時回傳 503 而非 200：健康檢查若只回報「行程還活著」，
    編排系統就無法察覺一個連不到資料庫、每個請求都失敗的實例。
    Phase 2 會一併加入 Redis 的檢查。
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
