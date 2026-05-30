"""
Database layer for Smart Web Scraper Suite.

Design decisions
────────────────
* `DatabaseManager` is a lightweight wrapper around sqlite3 that handles
  connection lifecycle, schema initialisation, and maintenance tasks.
* Connections are created per-request (Flask teardown) rather than shared
  globally, avoiding threading issues with SQLite's default check_same_thread.
* WAL journal mode is enabled for better read/write concurrency.
* `get_db()` uses Flask's `g` object so one connection is reused within a
  single request and automatically closed at teardown.
* Schema creation uses `CREATE TABLE IF NOT EXISTS`, making it safe to call
  on every startup without side effects.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


# ── Connection factory ─────────────────────────────────────────────────────────

def _make_connection(db_path: str, timeout: int = 30) -> sqlite3.Connection:
    """Open a new SQLite connection with production-safe settings."""
    conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL") # better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")  # enforce FK constraints
    conn.execute("PRAGMA synchronous=NORMAL")  # safe + faster than FULL
    return conn


# ── Flask integration helper ──────────────────────────────────────────────────

def get_db(app=None) -> sqlite3.Connection:
    """
    Return the per-request connection stored in Flask's `g`.

    Usage in a view or service:
        from database import get_db
        conn = get_db()
        rows = conn.execute("SELECT * FROM products").fetchall()

    The connection is closed automatically via `teardown_appcontext`.
    Register once in `create_app`:
        app.teardown_appcontext(close_db)
    """
    try:
        from flask import g, current_app
        if "db" not in g:
            g.db = _make_connection(
                current_app.config["DATABASE_PATH"],
                timeout=current_app.config.get("DATABASE_TIMEOUT", 30),
            )
        return g.db
    except RuntimeError:
        # Outside Flask app context (e.g. tests, CLI scripts)
        if app is None:
            raise
        return _make_connection(app.config["DATABASE_PATH"])


def close_db(exception=None) -> None:  # noqa: ARG001
    """Teardown callback — close the per-request connection."""
    try:
        from flask import g
        db = g.pop("db", None)
        if db is not None:
            db.close()
    except RuntimeError:
        pass


# ── Schema management ──────────────────────────────────────────────────────────

class DatabaseManager:
    """
    Manages schema creation, maintenance, and statistics.

    Intended to be instantiated once at app startup:
        db = DatabaseManager(config.DATABASE_PATH)
        db.init_schema()
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Public interface ───────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """Create all tables and indexes. Safe to call on every startup."""
        try:
            with self._managed_connection() as conn:
                self._create_price_tracker_tables(conn)
                self._create_seo_analyzer_tables(conn)
                self._create_data_scraper_tables(conn)
                self._create_general_tables(conn)
            logger.info("Database schema initialised | path=%s", self.db_path)
        except Exception:
            logger.exception("Failed to initialise database schema")
            raise

    def backup(self, backup_path: str | None = None) -> str:
        """Copy the live database to *backup_path* (or an auto-named file)."""
        if not backup_path:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = str(Path(self.db_path).parent / f"backup_{stamp}.db")

        Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        logger.info("Database backed up | destination=%s", backup_path)
        return backup_path

    def vacuum(self) -> None:
        """Reclaim unused pages. Run periodically via a scheduled task."""
        with self._managed_connection() as conn:
            conn.execute("VACUUM")
        logger.info("VACUUM completed | path=%s", self.db_path)

    def get_stats(self) -> dict:
        """Return row counts per table and the on-disk file size."""
        stats: dict = {}
        try:
            with self._managed_connection() as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()

                for (table_name,) in tables:
                    row = conn.execute(
                        f"SELECT COUNT(*) FROM {table_name}"  # noqa: S608
                    ).fetchone()
                    stats[table_name] = row[0] if row else 0

            size_bytes = Path(self.db_path).stat().st_size
            stats["database_size_bytes"] = size_bytes
            stats["database_size_mb"] = round(size_bytes / (1024 * 1024), 2)
        except Exception:
            logger.exception("Failed to gather database stats")
        return stats

    def cleanup_old_data(self, days_to_keep: int = 30) -> None:
        """
        Purge records older than *days_to_keep* days.
        System logs are retained for 7 days regardless of *days_to_keep*.
        """
        cutoff = f"-{days_to_keep} days"
        log_cutoff = "-7 days"
        try:
            with self._managed_connection() as conn:
                conn.execute(
                    "DELETE FROM price_history WHERE timestamp < datetime('now', ?)",
                    (cutoff,),
                )
                conn.execute(
                    "DELETE FROM seo_analyses WHERE analysis_date < datetime('now', ?)",
                    (cutoff,),
                )
                conn.execute(
                    "DELETE FROM scraping_sessions WHERE created_at < datetime('now', ?)",
                    (cutoff,),
                )
                conn.execute(
                    "DELETE FROM system_logs WHERE timestamp < datetime('now', ?)",
                    (log_cutoff,),
                )
                conn.execute(
                    "DELETE FROM api_usage_stats WHERE date < date('now', ?)",
                    (cutoff,),
                )
            logger.info("Old data purged | days_kept=%d", days_to_keep)
        except Exception:
            logger.exception("Failed to purge old data")
            raise

    # ── Internal helpers ───────────────────────────────────────────────────────

    @contextmanager
    def _managed_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager: yields a connection and commits/rolls back."""
        conn = _make_connection(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema builders ────────────────────────────────────────────────────────

    def _create_price_tracker_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT    UNIQUE NOT NULL,
                name             TEXT,
                current_price    REAL,
                original_price   REAL,
                target_price     REAL,
                rating           REAL,
                availability     TEXT,
                image_url        TEXT,
                platform         TEXT,
                status           TEXT    DEFAULT 'Tracking',
                total_savings    REAL    DEFAULT 0.0,
                last_updated     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL
                                REFERENCES products(id) ON DELETE CASCADE,
                price       REAL    NOT NULL,
                original_price REAL,
                change_percent REAL,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS price_alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id      INTEGER NOT NULL
                                    REFERENCES products(id) ON DELETE CASCADE,
                alert_type      TEXT    NOT NULL
                                    CHECK(alert_type IN
                                        ('price_drop','price_increase','availability')),
                threshold_value REAL,
                is_active       BOOLEAN DEFAULT 1,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id      INTEGER NOT NULL
                                    REFERENCES products(id) ON DELETE CASCADE,
                message         TEXT    NOT NULL,
                is_read         BOOLEAN DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_products_url
                ON products(url);
            CREATE INDEX IF NOT EXISTS idx_price_history_product_id
                ON price_history(product_id);
            CREATE INDEX IF NOT EXISTS idx_price_history_timestamp
                ON price_history(recorded_at);
        """)
        
        # Add missing columns to existing products table if they don't exist
        try:
            # Check and migrate products table
            columns = conn.execute("PRAGMA table_info(products)").fetchall()
            column_names = {col[1] for col in columns}
            
            if 'target_price' not in column_names:
                conn.execute("ALTER TABLE products ADD COLUMN target_price REAL")
            if 'image_url' not in column_names:
                conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
            if 'status' not in column_names:
                conn.execute("ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'Tracking'")
            if 'total_savings' not in column_names:
                conn.execute("ALTER TABLE products ADD COLUMN total_savings REAL DEFAULT 0.0")
            
            # Check and migrate price_history table
            columns = conn.execute("PRAGMA table_info(price_history)").fetchall()
            column_names = {col[1] for col in columns}
            
            if 'original_price' not in column_names:
                conn.execute("ALTER TABLE price_history ADD COLUMN original_price REAL")
            if 'change_percent' not in column_names:
                conn.execute("ALTER TABLE price_history ADD COLUMN change_percent REAL")
                
        except Exception as e:
            logger.warning(f"Could not migrate tables: {e}")

    def _create_seo_analyzer_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seo_analyses (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                url                 TEXT    NOT NULL,
                title               TEXT,
                description         TEXT,
                seo_score           INTEGER,
                word_count          INTEGER,
                heading_structure   TEXT,
                link_analysis       TEXT,
                image_analysis      TEXT,
                technical_analysis  TEXT,
                recommendations     TEXT,
                analysis_date       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS seo_keywords (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL
                                REFERENCES seo_analyses(id) ON DELETE CASCADE,
                keyword     TEXT    NOT NULL,
                frequency   INTEGER,
                density     REAL
            );

            CREATE INDEX IF NOT EXISTS idx_seo_analyses_url
                ON seo_analyses(url);
            CREATE INDEX IF NOT EXISTS idx_seo_analyses_date
                ON seo_analyses(analysis_date);
            CREATE INDEX IF NOT EXISTS idx_seo_keywords_analysis_id
                ON seo_keywords(analysis_id);
        """)

    def _create_data_scraper_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scraping_sessions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT    NOT NULL,
                scrape_type   TEXT    NOT NULL
                                  CHECK(scrape_type IN ('text','images','links','both')),
                status        TEXT    NOT NULL DEFAULT 'pending',
                files_created TEXT,
                images_count  INTEGER DEFAULT 0,
                text_length   INTEGER DEFAULT 0,
                error_message TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at  TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scraped_images (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL
                                 REFERENCES scraping_sessions(id) ON DELETE CASCADE,
                filename     TEXT,
                original_url TEXT,
                alt_text     TEXT,
                file_size    INTEGER,
                width        INTEGER,
                height       INTEGER,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_scraping_sessions_url
                ON scraping_sessions(url);
            CREATE INDEX IF NOT EXISTS idx_scraping_sessions_date
                ON scraping_sessions(created_at);
            CREATE INDEX IF NOT EXISTS idx_scraped_images_session_id
                ON scraped_images(session_id);
        """)

    def _create_general_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                level     TEXT    NOT NULL
                              CHECK(level IN
                                  ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
                module    TEXT,
                message   TEXT,
                details   TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                preference_key   TEXT UNIQUE NOT NULL,
                preference_value TEXT,
                updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS api_usage_stats (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint      TEXT    NOT NULL,
                request_count INTEGER DEFAULT 1,
                last_used     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date          DATE      DEFAULT CURRENT_DATE
            );

            CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp
                ON system_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_system_logs_level
                ON system_logs(level);
            CREATE INDEX IF NOT EXISTS idx_api_usage_stats_endpoint
                ON api_usage_stats(endpoint);
            CREATE INDEX IF NOT EXISTS idx_api_usage_stats_date
                ON api_usage_stats(date);
        """)