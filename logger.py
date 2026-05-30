"""
Centralised logging setup for Smart Web Scraper Suite.

Call `setup_logging(config)` once during app creation (inside
`create_app`).  Every other module then uses the standard
`logging.getLogger(__name__)` pattern — no further setup needed.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(config) -> None:
    """
    Configure the root logger from an application config object.

    Args:
        config: Any config class/instance that exposes
                LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_DIR.
    """
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt=config.LOG_FORMAT,
        datefmt=config.LOG_DATE_FORMAT,
    )

    handlers: list[logging.Handler] = []

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # ── Rotating file handler ─────────────────────────────────────────────────
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,   # 10 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    # ── Root logger ───────────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any handlers added by imported libraries before ours
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    # Silence noisy third-party loggers in production
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised | level=%s | file=%s",
        config.LOG_LEVEL,
        log_file,
    )