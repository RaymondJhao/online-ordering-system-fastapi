"""應用程式設定。

取代舊版 Flask 的 `app/config.py`（直接讀 os.environ、含 dev fallback）。

改用 pydantic-settings 的三個理由：
1. 型別轉換：`ACCESS_TOKEN_EXPIRE_MINUTES=15` 自動變成 int，不必到處寫 int(...)。
2. 啟動即驗證：設定錯誤在程式啟動時就炸掉，而不是等到第一個請求進來。
3. 沒有不安全的預設值：舊版 `os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-key")`
   會讓忘記設定環境變數的正式環境用一組公開在 GitHub 上的金鑰簽 JWT。
   這裡把金鑰設為必填欄位，缺少就啟動失敗。
"""

import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 常見的佔位字串。正式環境誤用這些值等同沒有設定金鑰，直接擋下。
_PLACEHOLDER_SECRETS = {
    "change-me",
    "changeme",
    "secret",
    "dev-secret-key",
    "dev-jwt-secret-key",
    "your-secret-key",
    "string",
}

_MIN_SECRET_LENGTH = 32


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 執行環境 ---
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    PROJECT_NAME: str = "線上點餐系統 API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api"

    # --- 安全性（必填：沒有預設值，缺少即啟動失敗）---
    SECRET_KEY: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: Annotated[int, Field(gt=0, le=1440)] = 15
    REFRESH_TOKEN_EXPIRE_DAYS: Annotated[int, Field(gt=0, le=90)] = 7

    # bcrypt 的成本因子。每 +1 代表運算時間加倍，12 約需 200~300ms。
    # 測試環境可調到 4 讓整套測試快上數十倍；下方的驗證會確保正式環境不會誤用低值。
    BCRYPT_ROUNDS: Annotated[int, Field(ge=4, le=16)] = 12

    # --- 外部服務 ---
    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn

    # --- CORS ---
    # NoDecode 讓 pydantic-settings 跳過預設的 JSON 解碼，把原始字串交給下面的
    # validator 處理。少了它，環境變數若不是合法 JSON（例如逗號分隔的寫法），
    # 會在 EnvSettingsSource 階段就拋 SettingsError，validator 根本不會被呼叫。
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # --- 綠界 ECPay ---
    ECPAY_MERCHANT_ID: str = "2000132"
    ECPAY_HASH_KEY: str = "5294y06JbISpM5x9"
    ECPAY_HASH_IV: str = "v77hoKGq4kWxNNIS"
    ECPAY_RETURN_URL: str = ""

    # --- 限流 ---
    RATE_LIMIT_ENABLED: bool = True

    # --- 背景排程 ---
    SCHEDULER_ENABLED: bool = True
    # 訂單建立後超過這個分鐘數仍未付款，就自動取消並釋放庫存
    UNPAID_ORDER_TIMEOUT_MINUTES: Annotated[int, Field(gt=0)] = 15
    # 排程檢查間隔
    SCHEDULER_INTERVAL_SECONDS: Annotated[int, Field(gt=0)] = 60

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """同時支援 JSON 陣列與逗號分隔兩種寫法。

            CORS_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173"]
            CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

        兩者都常見於教學與現有部署設定，接受兩種可以避免踩到
        「格式對了但沒人告訴你」的坑。
        """
        if not isinstance(value, str):
            return value

        text = value.strip()
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"CORS_ORIGINS 看起來是 JSON 陣列但格式有誤：{exc}。"
                    '請確認使用雙引號，例如 ["http://localhost:5173"]'
                ) from exc

        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_async_driver(cls, value: object) -> object:
        """把同步的 Postgres driver 補成 asyncpg。

        雲端平台（Render、Heroku、Railway…）注入的連線字串一律是
        `postgresql://` 或 `postgres://`，兩者對 async SQLAlchemy 都不可用，
        啟動時會拋 `InvalidRequestError: The asyncio extension requires an
        async driver`。這個錯誤訊息與「連線字串沒設對」看起來很像，
        實務上很容易在部署當下卡很久。

        在這裡統一正規化，等於讓平台的預設值直接可用。
        """
        if not isinstance(value, str):
            return value

        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
            if value.startswith(prefix):
                return value

        for legacy_prefix in ("postgresql://", "postgres://"):
            if value.startswith(legacy_prefix):
                return "postgresql+asyncpg://" + value[len(legacy_prefix) :]

        return value

    @field_validator("SECRET_KEY", "JWT_SECRET_KEY")
    @classmethod
    def _reject_weak_secrets(cls, value: str, info) -> str:
        """擋掉長度不足與範例佔位字串。

        這是舊版最實際的一個安全缺口：.env.example 裡寫 `SECRET_KEY=change-me`，
        只要有人照抄就會帶著可預測的金鑰上線，等於任何人都能自己簽出有效的 JWT。
        """
        if value.strip().lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                f"{info.field_name} 使用了範例佔位字串，請改為隨機值："
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if len(value) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"{info.field_name} 長度為 {len(value)}，至少需要 {_MIN_SECRET_LENGTH} 字元。"
            )
        return value

    @model_validator(mode="after")
    def _enforce_production_bcrypt_cost(self) -> Self:
        """正式環境不允許使用測試用的低成本因子。

        「測試環境調低 bcrypt rounds」是常見且合理的做法，但它的風險是
        設定被複製到正式環境而沒人察覺——密碼雜湊會變得可以暴力破解，
        且從外部完全看不出來。這裡讓錯誤設定在啟動時就失敗。
        """
        if self.ENVIRONMENT is Environment.PRODUCTION and self.BCRYPT_ROUNDS < 12:
            raise ValueError(f"正式環境的 BCRYPT_ROUNDS 不可低於 12（目前為 {self.BCRYPT_ROUNDS}）")
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def database_url_str(self) -> str:
        """SQLAlchemy 需要 str，PostgresDsn 物件不能直接餵給 create_async_engine。"""
        return str(self.DATABASE_URL)

    @property
    def redis_url_str(self) -> str:
        return str(self.REDIS_URL)


@lru_cache
def get_settings() -> Settings:
    """快取設定物件，避免每次注入都重讀 .env 並重跑驗證。

    刻意「不」在本模組底部寫 `settings = get_settings()`：那會讓 config 模組
    一旦被 import 就強制讀取環境變數，導致測試無法在不準備完整 .env 的情況下
    單獨驗證 Settings 的驗證規則。改由 `app/main.py` 在啟動時呼叫一次，
    fail-fast 的效果不變，但模組本身保持可被安全 import。

    測試需要覆寫設定時，用 `get_settings.cache_clear()` 或
    FastAPI 的 `app.dependency_overrides` 即可。
    """
    return Settings()  # type: ignore[call-arg]  # 值由 .env / 環境變數提供
