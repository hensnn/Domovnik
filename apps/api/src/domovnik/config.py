"""Konfigurace aplikace (z prostředí / .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-insecure-key-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://domovnik:domovnik_dev@localhost:5432/domovnik"
    # Klíč pro šifrování tajných hodnot v nastavení (Fernet, 32 B base64url).
    # V produkci MUSÍ být nastaven; vývojová výchozí hodnota je veřejně známá.
    secret_key: str = DEV_SECRET_KEY
    session_ttl_hours: int = 24 * 30
    cookie_secure: bool = False  # v produkci za HTTPS = True
    files_dir: str = "./data/files"
    domovnik_env: str = "development"  # production = přísnější kontroly při startu

    def check_production(self) -> None:
        """V produkci odmítne nebezpečnou konfiguraci (veřejně známý klíč, nezabezpečené cookie)."""
        if self.domovnik_env != "production":
            return
        if self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32:
            raise RuntimeError(
                "V produkci musí být SECRET_KEY nastaven na náhodnou hodnotu (min. 32 znaků)."
            )
        if "domovnik_dev" in self.database_url:
            raise RuntimeError("V produkci se nesmí použít vývojové heslo databáze.")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def to_sqlalchemy_url(url: str) -> str:
    """postgresql://… → postgresql+psycopg://… (SQLAlchemy ovladač psycopg 3)."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
