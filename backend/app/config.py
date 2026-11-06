import json
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOOPR_", env_file=".env", extra="ignore")
    env: str = "development"
    database_url: str = "sqlite:///./loopr.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 60 * 24 * 30
    otp_provider: str = "mock"  # mock | msg91 | twilio
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = "dev-webhook-secret"
    pricing_file: str = str(ROOT / "config" / "pricing.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_pricing() -> dict:
    """All prices/policies come from config, never from client code."""
    return json.loads(Path(get_settings().pricing_file).read_text(encoding="utf-8"))
