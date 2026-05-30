"""
Price Tracker Service Layer
============================
Handles all business logic for product scraping, price tracking,
database persistence, alerting, and reporting.

Architecture:
    - PriceTrackerService   : Orchestrates all operations (entry point for blueprints)
    - ProductScraper        : Isolated scraping logic with retry support
    - PlatformSelectors     : Centralised CSS selector registry (easy to extend)
    - PriceTrackerRepository: All DB access in one place (no raw SQL elsewhere)
    - GraphService          : Chart generation (separated from business logic)
    - ExportService         : CSV / JSON export helpers
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import matplotlib
matplotlib.use("Agg")                          # Non-interactive backend — safe for servers
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup
from flask import Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 12          # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0           # exponential-backoff multiplier
PRICE_DROP_ALERT_THRESHOLD = -5.0   # percent

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


# ---------------------------------------------------------------------------
# Data Transfer Objects  (plain dataclasses → easy serialisation)
# ---------------------------------------------------------------------------

@dataclass
class ProductData:
    """Scraped product snapshot."""
    url: str
    name: str
    price: float
    platform: str
    original_price: Optional[float] = None
    rating: Optional[float] = None
    availability: str = "Unknown"
    image_url: Optional[str] = None
    is_demo: bool = False           # True when real scraping failed

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PriceChange:
    """Delta between two consecutive price records."""
    previous_price: float
    current_price: float
    change: float
    percentage_change: float

    def is_significant(self, threshold: float = 5.0) -> bool:
        return abs(self.percentage_change) >= threshold


@dataclass
class DashboardStats:
    total_products: int = 0
    price_drops_today: int = 0
    active_alerts: int = 0
    total_savings: float = 0.0
    biggest_drop: dict = field(default_factory=lambda: {"name": None, "percent": 0})


# ---------------------------------------------------------------------------
# Platform Selector Registry
# ---------------------------------------------------------------------------

class PlatformSelectors:
    """
    Central registry of CSS selectors per platform.
    To add a new platform, just add a new key to each dict.
    """

    PLATFORM_DOMAINS: dict[str, str] = {
        "amazon": "amazon",
        "flipkart": "flipkart",
        "ebay": "ebay",
    }

    NAME: dict[str, list[str]] = {
        "amazon": [
            "#productTitle", ".product-title", "h1[data-asin]",
            "#title h1", "#productTitle span", "[data-automation-id='title']",
        ],
        "flipkart": [".B_NuCI", ".pdp-name", "h1", ".product-title"],
        "ebay": ["#x-title-label", ".u-titleL", "h1", ".item-title"],
        "generic": [
            "h1", ".product-title", ".title",
            "[data-testid='product-title']", ".product-name",
        ],
    }

    PRICE: dict[str, list[str]] = {
        "amazon": [
            ".a-price-whole", ".a-offscreen",
            ".a-price .a-price-range", ".a-price .a-offscreen",
        ],
        "flipkart": [".Nx9bqj", "._30jeq3", ".price", ".current-price"],
        "ebay": [".u-priceL", ".display-price", ".price-now", ".price"],
        "generic": [
            ".price", ".current-price", ".sale-price",
            "[data-price]", ".product-price", ".actual-price",
        ],
    }

    ORIGINAL_PRICE: dict[str, list[str]] = {
        "amazon": [".a-price.a-text-price .a-offscreen", ".basisPrice"],
        "flipkart": ["._3I9_wc", ".original-price"],
        "ebay": [".u-priceL .strikethrough", ".original-price"],
        "generic": [
            ".original-price", ".list-price",
            ".was-price", ".compare-at-price",
        ],
    }

    RATING: dict[str, list[str]] = {
        "amazon": [".a-icon-alt", "[data-hook='average-star-rating']"],
        "flipkart": ["._2L_RQ9", ".rating"],
        "ebay": [".reviews-star-rating", ".rating"],
        "generic": [".rating", ".stars", ".review-score", "[data-rating]"],
    }

    AVAILABILITY: dict[str, list[str]] = {
        "amazon": [
            "#availability .a-color-success",
            "#availability .a-color-state",
        ],
        "flipkart": ["._16FRp0", ".availability"],
        "ebay": [".u-flg-cond", ".availability"],
        "generic": [".availability", ".stock-status", "[data-availability]"],
    }

    IMAGE: dict[str, list[str]] = {
        "amazon": [
            "#landingImage", ".a-dynamic-image", "#imgBlkFront",
            "#main-image-container img",
            "[data-action='main-image-click'] img",
        ],
        "flipkart": [
            "._396cs4", ".product-image img",
            "._2r_-D4 img", ".q6DClP img",
        ],
        "ebay": [
            ".ux-image-carousel img",
            ".image-treatment img",
            ".ux-image-carousel-item img",
        ],
        "generic": [
            ".product-image img", ".main-image img",
            ".primary-image img", ".gallery-image img",
        ],
    }

    @classmethod
    def for_platform(cls, platform: str, selector_map: dict) -> list[str]:
        return selector_map.get(platform, selector_map.get("generic", []))


# ---------------------------------------------------------------------------
# Repository  (all SQLite access lives here)
# ---------------------------------------------------------------------------

class PriceTrackerRepository:
    """
    Thin data-access layer.  Every public method maps to one logical DB
    operation; callers never write raw SQL.
    """

    # Column name tuples used for row → dict conversion
    _PRODUCT_COLS = (
        "id", "url", "name", "current_price", "original_price",
        "target_price", "rating", "availability", "image_url",
        "platform", "created_at", "last_updated", "status", "total_savings",
    )

    def __init__(self) -> None:
        # Database is now managed by the app factory
        pass
    
    def _get_db(self):
        """Get database connection using Flask app context."""
        from database import get_db
        return get_db()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self):
        """Yield a connection and guarantee commit-or-rollback."""
        from database import get_db
        db = get_db()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def upsert_product(
        self,
        product: ProductData,
        target_price: Optional[float] = None,
    ) -> int:
        """Insert or update product; add a price_history row; fire alerts. Returns product_id."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, current_price FROM products WHERE url = ?",
                (product.url,),
            )
            existing = cursor.fetchone()

            if existing:
                product_id, old_price = existing
                change_pct = (
                    (product.price - old_price) / old_price * 100
                    if old_price > 0
                    else 0.0
                )
                savings_delta = max(0.0, old_price - product.price)

                # Derive status
                status = "Tracking"
                if target_price and product.price <= target_price:
                    status = "Target Hit"
                elif change_pct < 0:
                    status = "Price Drop"

                cursor.execute(
                    """
                    UPDATE products SET
                        name = ?, current_price = ?, original_price = ?,
                        rating = ?, availability = ?, image_url = ?,
                        platform = ?, target_price = ?,
                        last_updated = CURRENT_TIMESTAMP,
                        total_savings = total_savings + ?,
                        status = ?
                    WHERE id = ?
                    """,
                    (
                        product.name, product.price, product.original_price,
                        product.rating, product.availability, product.image_url,
                        product.platform, target_price,
                        savings_delta, status,
                        product_id,
                    ),
                )
            else:
                change_pct = 0.0
                cursor.execute(
                    """
                    INSERT INTO products
                        (url, name, current_price, original_price, rating,
                         availability, image_url, platform, target_price, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Tracking')
                    """,
                    (
                        product.url, product.name, product.price,
                        product.original_price, product.rating,
                        product.availability, product.image_url,
                        product.platform, target_price,
                    ),
                )
                product_id = cursor.lastrowid

            # Price history row
            cursor.execute(
                """
                INSERT INTO price_history
                    (product_id, price, original_price, change_percent, timestamp)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (product_id, product.price, product.original_price, change_pct),
            )

            # Alerts (inside the same connection/transaction)
            self._create_alerts(cursor, product_id, product.price, target_price, change_pct)

        return product_id

    def get_product_by_id(self, product_id: int) -> Optional[dict]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {', '.join(self._PRODUCT_COLS)} FROM products WHERE id = ?",
                (product_id,),
            )
            row = cursor.fetchone()
        if row:
            return dict(zip(self._PRODUCT_COLS, row))
        return None

    def get_all_products(self) -> list[dict]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT {', '.join(self._PRODUCT_COLS)},
                    (SELECT change_percent FROM price_history
                     WHERE product_id = p.id
                     ORDER BY timestamp DESC LIMIT 1) AS price_change
                FROM products p
                ORDER BY last_updated DESC
                """
            )
            cols = list(self._PRODUCT_COLS) + ["price_change"]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def delete_product(self, product_id: int) -> bool:
        """Returns True if a row was deleted."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_price_history(self, product_id: int, limit: int = 30) -> list[dict]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT price, original_price, change_percent, timestamp
                FROM price_history
                WHERE product_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (product_id, limit),
            )
            cols = ("price", "original_price", "change_percent", "timestamp")
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_last_two_prices(self, product_id: int) -> list[float]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT price FROM price_history
                WHERE product_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
                """,
                (product_id,),
            )
            return [row[0] for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> dict:
        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM products")
            total_products = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM price_history
                WHERE DATE(timestamp) = DATE('now') AND change_percent < ?
                """,
                (PRICE_DROP_ALERT_THRESHOLD,),
            )
            price_drops_today = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM alerts WHERE is_read = 0")
            active_alerts = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COALESCE(SUM(original_price - current_price), 0)
                FROM products WHERE original_price > current_price
                """
            )
            total_savings = round(cursor.fetchone()[0], 2)

            cursor.execute(
                """
                SELECT p.name, ph.change_percent
                FROM price_history ph
                JOIN products p ON ph.product_id = p.id
                WHERE ph.change_percent < 0
                ORDER BY ph.change_percent ASC
                LIMIT 1
                """
            )
            biggest_drop_row = cursor.fetchone()

        return DashboardStats(
            total_products=total_products,
            price_drops_today=price_drops_today,
            active_alerts=active_alerts,
            total_savings=total_savings,
            biggest_drop={
                "name": biggest_drop_row[0] if biggest_drop_row else None,
                "percent": round(biggest_drop_row[1], 1) if biggest_drop_row else 0,
            },
        ).__dict__

    # ------------------------------------------------------------------
    # Alerts (internal helper — called inside upsert_product's transaction)
    # ------------------------------------------------------------------

    @staticmethod
    def _create_alerts(
        cursor,
        product_id: int,
        current_price: float,
        target_price: Optional[float],
        change_percent: float,
    ) -> None:
        if target_price and current_price <= target_price:
            cursor.execute(
                """
                INSERT INTO alerts (product_id, alert_type, message, price, target_price)
                VALUES (?, 'target_hit', ?, ?, ?)
                """,
                (product_id, f"Target price of ${target_price:.2f} reached!", current_price, target_price),
            )

        if change_percent < PRICE_DROP_ALERT_THRESHOLD:
            cursor.execute(
                """
                INSERT INTO alerts (product_id, alert_type, message, price)
                VALUES (?, 'price_drop', ?, ?)
                """,
                (product_id, f"Price dropped by {abs(change_percent):.1f}%", current_price),
            )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class ProductScraper:
    """
    Responsible solely for fetching a URL and extracting a ProductData.
    Retry logic is self-contained; callers just call `scrape(url)`.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape(self, url: str) -> ProductData:
        """
        Fetch the product page and extract fields.
        Raises ValueError on permanent failures; callers should catch it.
        """
        html = self._fetch_with_retry(url)
        soup = BeautifulSoup(html, "html.parser")
        platform = self._detect_platform(url)
        logger.info("Detected platform '%s' for %s", platform, url)

        name = self._extract_name(soup, platform)
        price = self._extract_price(soup, platform)
        original_price = self._extract_original_price(soup, platform)
        rating = self._extract_rating(soup, platform)
        availability = self._extract_availability(soup, platform)
        image_url = self._extract_image_url(soup, platform, url)

        # Fall back to demo data when critical fields are missing
        if not name or not price:
            logger.warning("Real extraction incomplete for %s — using demo fallback.", url)
            return self._demo_fallback(url, platform, partial_name=name)

        logger.info("Scraped '%s' @ $%.2f from %s", name, price, platform)
        return ProductData(
            url=url,
            name=name,
            price=price,
            platform=platform,
            original_price=original_price,
            rating=rating,
            availability=availability,
            image_url=image_url,
        )

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------

    def _fetch_with_retry(self, url: str) -> bytes:
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.content
            except requests.exceptions.HTTPError as exc:
                # Don't retry client-side errors (4xx) — they won't resolve
                if exc.response is not None and exc.response.status_code < 500:
                    raise ValueError(f"HTTP {exc.response.status_code} for {url}") from exc
                last_exc = exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc

            wait = RETRY_BACKOFF ** attempt
            logger.warning(
                "Fetch attempt %d/%d failed for %s — retrying in %.1fs: %s",
                attempt, MAX_RETRIES, url, wait, last_exc,
            )
            time.sleep(wait)

        raise ValueError(f"All {MAX_RETRIES} fetch attempts failed for {url}: {last_exc}")

    # ------------------------------------------------------------------
    # Platform detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_platform(url: str) -> str:
        domain = urlparse(url).netloc.lower()
        for platform, keyword in PlatformSelectors.PLATFORM_DOMAINS.items():
            if keyword in domain:
                return platform
        return "generic"

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_text(element) -> str:
        """Extract stripped text from a BS4 element without get_text()."""
        if not element:
            return ""
        try:
            return " ".join(str(s) for s in element.stripped_strings).strip()
        except Exception:
            return str(getattr(element, "string", "") or "").strip()

    def _extract_name(self, soup: BeautifulSoup, platform: str) -> Optional[str]:
        skip_words = {"account", "help", "cart", "search", "home", "menu"}

        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.NAME):
            el = soup.select_one(sel)
            if el:
                text = self._safe_text(el)
                if len(text) > 5 and not any(w in text.lower() for w in skip_words):
                    return text

        # Amazon h1 fallback
        if platform == "amazon":
            for h1 in soup.find_all("h1"):
                text = self._safe_text(h1)
                if len(text) > 10 and "amazon" not in text.lower():
                    text = re.sub(r"\s*[-|]\s*Amazon\.com.*$", "", text, flags=re.IGNORECASE)
                    if len(text) > 10:
                        return text.strip()

        # <title> tag last resort
        if soup.title and soup.title.string:
            title = re.sub(
                r"\s*[-|]\s*(Amazon|eBay|Flipkart|Walmart|Target|Best Buy).*$",
                "",
                soup.title.string.strip(),
                flags=re.IGNORECASE,
            ).strip()
            if len(title) > 10:
                return title

        # og:title meta
        og = soup.find("meta", property="og:title")
        if og and og.get("content") and len(og["content"].strip()) > 5:
            return og["content"].strip()

        return None

    def _extract_price(self, soup: BeautifulSoup, platform: str) -> Optional[float]:
        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.PRICE):
            for el in soup.select(sel):
                price = self._parse_price(self._safe_text(el))
                if price and price > 0:
                    return price

        # Regex fallback over full page text
        try:
            page_text = " ".join(str(s) for s in soup.stripped_strings)
        except Exception:
            return None

        for pattern in [
            r"\$(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)",
            r"(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)\s*USD",
        ]:
            matches = re.findall(pattern, page_text)
            for m in matches:
                price = self._parse_price(m)
                if price and 0 < price < 100_000:
                    return price

        return None

    def _extract_original_price(self, soup: BeautifulSoup, platform: str) -> Optional[float]:
        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.ORIGINAL_PRICE):
            el = soup.select_one(sel)
            if el:
                price = self._parse_price(self._safe_text(el))
                if price:
                    return price
        return None

    def _extract_rating(self, soup: BeautifulSoup, platform: str) -> Optional[float]:
        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.RATING):
            el = soup.select_one(sel)
            if el:
                rating = self._parse_rating(self._safe_text(el))
                if rating:
                    return rating
        return None

    def _extract_availability(self, soup: BeautifulSoup, platform: str) -> str:
        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.AVAILABILITY):
            el = soup.select_one(sel)
            if el:
                text = self._safe_text(el).lower()
                if "in stock" in text or "available" in text:
                    return "In Stock"
                if "out of stock" in text or "unavailable" in text:
                    return "Out of Stock"
        return "Unknown"

    def _extract_image_url(
        self, soup: BeautifulSoup, platform: str, page_url: str
    ) -> Optional[str]:
        image_attrs = ("src", "data-src", "data-original", "data-lazy", "data-iurl")
        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

        def _normalise(img_url: str) -> Optional[str]:
            if not img_url or not img_url.strip():
                return None
            if img_url.startswith("//"):
                return "https:" + img_url
            if img_url.startswith("/"):
                parsed = urlparse(page_url)
                return f"{parsed.scheme}://{parsed.netloc}{img_url}"
            return img_url

        for sel in PlatformSelectors.for_platform(platform, PlatformSelectors.IMAGE):
            el = soup.select_one(sel)
            if el:
                for attr in image_attrs:
                    raw = el.get(attr)
                    if raw:
                        url = _normalise(raw)
                        if url and any(url.lower().endswith(ext) for ext in valid_exts):
                            return url

        # Keyword heuristic over all images
        for img in soup.find_all("img"):
            for attr in image_attrs:
                raw = img.get(attr)
                if raw and any(kw in raw.lower() for kw in ("product", "main", "primary", "hero")):
                    url = _normalise(raw)
                    if url:
                        return url

        # og:image last resort
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]

        return None

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_price(text: str) -> Optional[float]:
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    @staticmethod
    def _parse_rating(text: str) -> Optional[float]:
        m = re.search(r"(\d+\.?\d*)", text)
        if m:
            try:
                return min(float(m.group(1)), 5.0)
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # Demo fallback
    # ------------------------------------------------------------------

    _DEMO_CATALOGUE: dict[str, dict] = {
        "B08L5YPJ2K": {
            "name": "Apple iPhone 15 Pro Max (256 GB) – Blue Titanium",
            "price": 1199.99,
            "original_price": 1299.99,
            "rating": 4.8,
            "image_url": "https://via.placeholder.com/300x300/0071E3/FFFFFF?text=iPhone+15+Pro+Max",
        },
        "B0FQFQF6D1": {
            "name": "Apple iPhone 17 Pro Max (512 GB) – Natural Titanium",
            "price": 1549.00,
            "original_price": 1699.00,
            "rating": 4.9,
            "image_url": "https://via.placeholder.com/300x300/0071E3/FFFFFF?text=iPhone+17+Pro+Max",
        },
    }

    _KEYWORD_DEFAULTS: list[tuple[str, str, str]] = [
        ("iphone", "Apple iPhone", "0071E3"),
        ("samsung", "Samsung Galaxy", "1428A0"),
        ("laptop", "Premium Laptop", "64748B"),
    ]

    def _demo_fallback(
        self,
        url: str,
        platform: str,
        partial_name: Optional[str] = None,
    ) -> ProductData:
        # Try ASIN lookup first
        asin_match = re.search(r"/dp/([A-Z0-9]{10})", url)
        asin = asin_match.group(1) if asin_match else None
        catalogue_entry = self._DEMO_CATALOGUE.get(asin) if asin else None

        if catalogue_entry:
            data = catalogue_entry.copy()
        else:
            data = {"price": 999.99, "original_price": 1299.99, "rating": 4.5}
            url_lower = url.lower()
            for keyword, name, color in self._KEYWORD_DEFAULTS:
                if keyword in url_lower:
                    data["name"] = partial_name or name
                    data["image_url"] = (
                        f"https://via.placeholder.com/300x300/{color}/FFFFFF"
                        f"?text={name.replace(' ', '+')}"
                    )
                    break
            else:
                data.setdefault("name", partial_name or "Amazon Product")
                data.setdefault(
                    "image_url",
                    "https://via.placeholder.com/300x300/FF9900/FFFFFF?text=Product",
                )

        return ProductData(
            url=url,
            name=data["name"],
            price=data["price"],
            platform=platform,
            original_price=data.get("original_price"),
            rating=data.get("rating"),
            availability="In Stock",
            image_url=data.get("image_url"),
            is_demo=True,
        )


# ---------------------------------------------------------------------------
# Graph Service
# ---------------------------------------------------------------------------

class GraphService:
    """Generates and persists price-history charts."""

    GRAPH_DIR = "static/images"

    @classmethod
    def generate(cls, product_id: int, price_history: list[dict]) -> Optional[str]:
        """
        Returns the web-relative path to the saved PNG, or None on failure.
        price_history entries: {price, timestamp} — newest first (as returned by repo).
        """
        if not price_history:
            logger.warning("No price history for product %d — skipping graph.", product_id)
            return None

        try:
            # Reverse to chronological order
            entries = list(reversed(price_history))
            dates = [datetime.fromisoformat(e["timestamp"]) for e in entries]
            prices = [e["price"] for e in entries]

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.plot(dates, prices, marker="o", linewidth=2, markersize=4, color="#4F46E5")
            ax.set_title("Price History", fontsize=16, fontweight="bold", pad=20)
            ax.set_xlabel("Date", fontsize=12)
            ax.set_ylabel("Price ($)", fontsize=12)
            ax.grid(True, alpha=0.3)
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax.xaxis.set_major_locator(
                mdates.DayLocator(interval=max(1, len(dates) // 10))
            )
            plt.xticks(rotation=45)

            # Sparse price labels
            step = max(1, len(dates) // 5)
            for i, (d, p) in enumerate(zip(dates, prices)):
                if i % step == 0:
                    ax.annotate(
                        f"${p:,.0f}", (d, p),
                        textcoords="offset points", xytext=(0, 10),
                        ha="center", fontsize=8, alpha=0.8,
                    )

            fig.tight_layout()

            os.makedirs(cls.GRAPH_DIR, exist_ok=True)
            filename = f"price_graph_{product_id}.png"
            filepath = os.path.join(cls.GRAPH_DIR, filename)
            fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white")
            plt.close(fig)

            logger.info("Saved price graph → %s", filepath)
            return f"/static/images/{filename}"

        except Exception:
            logger.exception("Failed to generate price graph for product %d.", product_id)
            return None


# ---------------------------------------------------------------------------
# Export Service
# ---------------------------------------------------------------------------

class ExportService:
    """Converts product lists into Flask Response objects (CSV / JSON)."""

    _CSV_HEADERS = [
        "ID", "Name", "Current Price", "Original Price", "Target Price",
        "Rating", "Availability", "Platform", "Last Updated", "Status", "Total Savings",
    ]
    _CSV_FIELDS = [
        "id", "name", "current_price", "original_price", "target_price",
        "rating", "availability", "platform", "last_updated", "status", "total_savings",
    ]

    @classmethod
    def to_csv_response(cls, products: list[dict]) -> Optional[Response]:
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(cls._CSV_HEADERS)
            for p in products:
                writer.writerow([p.get(f) for f in cls._CSV_FIELDS])
            buf.seek(0)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=products.csv"},
            )
        except Exception:
            logger.exception("Failed to build CSV export.")
            return None

    @classmethod
    def to_json_response(cls, products: list[dict]) -> Optional[Response]:
        try:
            return Response(
                json.dumps(products, indent=2, default=str),
                mimetype="application/json",
                headers={"Content-Disposition": "attachment; filename=products.json"},
            )
        except Exception:
            logger.exception("Failed to build JSON export.")
            return None

# Main Service  (the only class blueprints should import)
# ---------------------------------------------------------------------------

class PriceTrackerService:
    """
    Facade that wires together the scraper, repository, graph and export
    services.  Blueprints and routes should only depend on this class.

    Usage:
        service = PriceTrackerService(config)                 # uses config from app
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._repo = PriceTrackerRepository()
        self._scraper = ProductScraper()
        self._graph_service = GraphService()
        self._export_service = ExportService()

    # ------------------------------------------------------------------
    # Core tracking
    # ------------------------------------------------------------------

    def track_price(self, url: str, target_price: Optional[float] = None) -> dict:
        """
        Scrape the product URL, persist the result, and return a summary dict.
        Always returns a dict — callers should check for 'error' key.
        """
        if not self._is_valid_url(url):
            return {"error": "Invalid URL format."}

        try:
            product = self._scraper.scrape(url)
        except ValueError as exc:
            logger.error("Scraping failed for %s: %s", url, exc)
            return {"error": str(exc)}
        except Exception:
            logger.exception("Unexpected error while scraping %s.", url)
            return {"error": "An unexpected error occurred during scraping."}

        try:
            product_id = self._repo.upsert_product(product, target_price)
        except Exception:
            logger.exception("Failed to persist product data for %s.", url)
            return {"error": "Failed to save product data."}

        price_change = self._compute_price_change(product_id, product.price)
        history = self._repo.get_price_history(product_id)

        if price_change and price_change.is_significant():
            logger.info(
                "Significant price change for product %d: %.2f%%",
                product_id, price_change.percentage_change,
            )

        return {
            "product_id": product_id,
            "product": product.to_dict(),
            "price_change": price_change.__dict__ if price_change else None,
            "history": history,
            "timestamp": datetime.now().isoformat(),
        }

    def save_product(self, product_data: dict, target_price: Optional[float] = None, email: Optional[str] = None) -> dict:
        """
        Persist an already-scraped product dict (e.g. passed from the blueprint).
        Validates required fields before touching the DB.
        """
        required = ("url", "name", "price")
        for field_name in required:
            if not product_data.get(field_name):
                return {"error": f"Missing required field: '{field_name}'."}

        try:
            product = ProductData(**{k: product_data.get(k) for k in ProductData.__dataclass_fields__})  # type: ignore[attr-defined]
        except TypeError as exc:
            return {"error": f"Invalid product data: {exc}"}

        try:
            product_id = self._repo.upsert_product(product, target_price)
            return {"product_id": product_id}
        except Exception:
            logger.exception("save_product DB error.")
            return {"error": "Database error while saving product."}

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_products(self) -> list[dict]:
        return self._repo.get_all_products()

    def get_product_by_id(self, product_id: int) -> Optional[dict]:
        return self._repo.get_product_by_id(product_id)

    def get_price_history(self, product_id: int, limit: int = 30) -> list[dict]:
        return self._repo.get_price_history(product_id, limit)

    def get_statistics(self) -> dict:
        return self._repo.get_statistics()

    # ------------------------------------------------------------------
    # Write / delete
    # ------------------------------------------------------------------

    def delete_product(self, product_id: int) -> dict:
        try:
            deleted = self._repo.delete_product(product_id)
            if deleted:
                logger.info("Deleted product %d.", product_id)
                return {}
            return {"error": f"Product {product_id} not found."}
        except Exception:
            logger.exception("Error deleting product %d.", product_id)
            return {"error": "Database error while deleting product."}

    # ------------------------------------------------------------------
    # Graphs & exports
    # ------------------------------------------------------------------

    def generate_price_graph(self, product_id: int) -> Optional[str]:
        history = self._repo.get_price_history(product_id)
        return GraphService.generate(product_id, history)

    def export_to_csv(self, products: Optional[list[dict]] = None) -> Optional[Response]:
        if products is None:
            products = self._repo.get_all_products()
        return ExportService.to_csv_response(products)

    def export_to_json(self, products: Optional[list[dict]] = None) -> Optional[Response]:
        if products is None:
            products = self._repo.get_all_products()
        return ExportService.to_json_response(products)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc)
        except Exception:
            return False

    def _compute_price_change(
        self, product_id: int, current_price: float
    ) -> Optional[PriceChange]:
        prices = self._repo.get_last_two_prices(product_id)
        if len(prices) >= 2:
            previous = prices[1]
            delta = current_price - previous
            pct = (delta / previous * 100) if previous > 0 else 0.0
            return PriceChange(
                previous_price=previous,
                current_price=current_price,
                change=delta,
                percentage_change=pct,
            )
        return None