"""Konfigurace aplikace (z prostředí / .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://domovnik:domovnik_dev@localhost:5432/domovnik"
    # Klíč pro šifrování tajných hodnot v nastavení (Fernet, 32 B base64url).
    # V produkci MUSÍ být nastaven; vývojová výchozí hodnota je veřejně známá.
    secret_key: str = "dev-only-insecure-key-change-me"
    session_ttl_hours: int = 24 * 30
    cookie_secure: bool = False  # v produkci za HTTPS = True
    files_dir: str = "./data/files"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def to_sqlalchemy_url(url: str) -> str:
    """postgresql://… → postgresql+psycopg://… (SQLAlchemy ovladač psycopg 3)."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
