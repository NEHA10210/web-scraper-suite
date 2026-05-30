"""
Application configuration — environment-based, production-ready.

Usage:
    app.config.from_object(get_config())

Set APP_ENV=production (or staging / testing) in your environment.
All secrets come from env vars; no hardcoded values.
"""

import os
from pathlib import Path

# Load .env file if it exists - MUST be at the top before any config classes
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed - rely on system environment
    pass

BASE_DIR = Path(__file__).resolve().parent


class BaseConfig:
    # ── Core ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
    DEBUG: bool = False
    TESTING: bool = False

    # ── Paths ─────────────────────────────────────────────────────────────────
    DATA_DIR: Path = BASE_DIR / "data"
    LOG_DIR: Path = BASE_DIR / "logs"
    STATIC_IMAGE_DIR: Path = BASE_DIR / "static" / "images"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_PATH: str = str(BASE_DIR / "data" / "scraper_suite.db")
    # SQLite WAL mode + 30-second busy timeout for production concurrency
    DATABASE_TIMEOUT: int = 30
    DATABASE_WAL_MODE: bool = True

    # ── File upload ───────────────────────────────────────────────────────────
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16 MB

    # ── Scraping ──────────────────────────────────────────────────────────────
    SCRAPER_REQUEST_TIMEOUT: int = 30           # seconds
    SCRAPER_MAX_RETRIES: int = 3
    SCRAPER_RETRY_BACKOFF: float = 1.5          # exponential base
    SCRAPER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    SUPPORTED_ECOMMERCE_SITES: list = ["amazon", "flipkart", "ebay", "example"]

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    @classmethod
    def ensure_directories(cls) -> None:
        """Create required runtime directories if they do not exist."""
        for directory in (cls.DATA_DIR, cls.LOG_DIR, cls.STATIC_IMAGE_DIR):
            Path(directory).mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"


class TestingConfig(BaseConfig):
    TESTING: bool = True
    DATABASE_PATH: str = ":memory:"
    LOG_LEVEL: str = "WARNING"


class ProductionConfig(BaseConfig):
    # In production every secret MUST come from the environment.
    SECRET_KEY: str = os.environ["SECRET_KEY"]          # hard fail if missing
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "WARNING")


_CONFIG_MAP: dict = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config() -> type:
    """Return the config class for the current APP_ENV (default: development)."""
    env = os.environ.get("APP_ENV", "development").lower()
    config_class = _CONFIG_MAP.get(env)
    if config_class is None:
        raise ValueError(
            f"Unknown APP_ENV '{env}'. Choose from: {list(_CONFIG_MAP)}"
        )
    return config_class