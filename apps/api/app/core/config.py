from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = ROOT / "data" / "ifbuy.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ifbuy_db: str = str(DEFAULT_DB)
    ifbuy_token: str | None = None
    ifbuy_tushare_token: str | None = None
    price_drift_bps: int = 50  # 0.5%
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:8080,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
