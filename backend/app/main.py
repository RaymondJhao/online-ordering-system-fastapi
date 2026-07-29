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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Environment, get_settings

# 在此呼叫一次：設定有誤時，應用程式會在啟動階段就失敗，而不是等到第一個請求。
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """應用程式啟動與關閉時執行的工作。

    Phase 0 先留空骨架；後續階段會在這裡接上：
      - Phase 1：資料庫連線池的建立與關閉
      - Phase 2：Redis 連線池（JWT blocklist 用）
      - Phase 4：AsyncIOScheduler 背景排程、fastapi-limiter 初始化
    """
    # --- startup ---
    yield
    # --- shutdown ---


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


@app.get("/health", tags=["System"], summary="健康檢查")
async def health_check() -> dict[str, str]:
    """回報服務存活狀態，供容器編排與 Render 的健康檢查使用。

    Phase 1 會擴充為同時檢查資料庫與 Redis 的連線狀態。
    """
    return {
        "status": "ok",
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
