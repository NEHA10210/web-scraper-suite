"""
Clean Data Scraper Service - Original working version
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import concurrent.futures
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT    = 15          # seconds — page fetch
IMAGE_TIMEOUT      = 10          # seconds — individual image fetch
MAX_RETRIES        = 3
RETRY_BACKOFF      = 2.0         # exponential-backoff base
IMAGE_DOWNLOAD_CAP = 20          # max images downloaded per scrape call
IMAGE_RATE_LIMIT   = 0.5         # seconds between image downloads

NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside"]

VALID_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

DATE_META_SELECTORS = [
    'meta[property="article:published_time"]',
    'meta[name="date"]',
    'meta[name="publish_date"]',
    'meta[property="datePublished"]',
]

# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------

@dataclass
class PageMetadata:
    url: str
    title: str = ""
    description: str = ""
    author: str = ""
    publish_date: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TextStats:
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    paragraph_count: int = 0
    sentence_count: int = 0
    avg_words_per_sentence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TextResult:
    url: str
    title: str
    text: str
    stats: TextStats
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    saved_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImageInfo:
    src: str
    alt: str = ""
    title: str = ""
    width: Optional[str] = None
    height: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DownloadedImage:
    filename: str
    filepath: str
    size_bytes: int
    data_url: str
    original_src: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImageResult:
    total_found: int
    downloaded: int
    total_size_mb: float
    downloaded_images: list[dict]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    saved_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Page Fetcher  (HTTP + retry)
# ---------------------------------------------------------------------------

class PageFetcher:
    """Simple HTTP client with retry logic and a browser-like User-Agent."""

    def __init__(self, timeout: int = REQUEST_TIMEOUT, max_retries: int = MAX_RETRIES):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)

    def fetch_page(self, url: str) -> bytes:
        """Fetch a page and return its raw bytes."""
        for attempt in range(self.max_retries):
            try:
                response = self._session.get(url, timeout=self.timeout)
                response.raise_for_status()
                logger.debug("Fetched %s (status: %d, size: %d bytes)", url, response.status_code, len(response.content))
                return response.content
            except requests.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise ValueError(f"Failed to fetch {url} after {self.max_retries} attempts: {exc}") from exc
                wait = RETRY_BACKOFF * (2 ** attempt)
                logger.warning("Attempt %d failed for %s: %s. Retrying in %.1fs...", attempt + 1, url, exc, wait)
                time.sleep(wait)

    def fetch_binary(self, url: str) -> bytes:
        """Fetch binary data (used for images)."""
        try:
            response = self._session.get(url, timeout=IMAGE_TIMEOUT, stream=True)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise ValueError(f"Failed to fetch binary from {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# Dynamic Page Fetcher (Playwright-based)
# ---------------------------------------------------------------------------

class DynamicPageFetcher:
    """Handles dynamic content scraping using Playwright."""
    
    def __init__(self, timeout: int = 15, wait_for: str = None):
        self.timeout = timeout * 1000  # Playwright uses milliseconds
        self.wait_for = wait_for
        self._browser = None
        self._playwright = None
        self._context = None
        
    def _init_browser(self):
        """Initialize Playwright browser if not already done."""
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._context = self._browser.new_context()
                logger.info("DynamicPageFetcher: Initialized headless Chromium browser")
            except ImportError:
                raise ImportError(
                    "Playwright not installed. Install with: "
                    "pip install playwright && playwright install chromium"
                )
            except Exception as e:
                logger.error("Failed to initialize Playwright browser: %s", e)
                raise
    
    def fetch_page(self, url: str) -> bytes:
        """Fetch a page using Playwright and return HTML bytes."""
        self._init_browser()

        page = None
        try:
            # Create a new page in the context
            page = self._context.new_page()

            # Set realistic viewport and user agent
            page.set_viewport_size({"width": 1366, "height": 768})
            page.set_extra_http_headers({
                "User-Agent": BROWSER_HEADERS["User-Agent"],
            })

            # Navigate to the page (hard timeout enforced by Playwright)
            logger.info("DynamicPageFetcher: Loading page %s", url)
            response = page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")

            if response is None:
                raise ValueError(f"Failed to load page: {url}")

            # Wait for specific content if specified
            if self.wait_for:
                try:
                    page.wait_for_selector(self.wait_for, timeout=self.timeout)
                    logger.debug("DynamicPageFetcher: Waited for selector: %s", self.wait_for)
                except Exception:
                    logger.warning("DynamicPageFetcher: Selector not found: %s", self.wait_for)

            # Wait for network to be mostly idle (good for dynamic sites)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Small extra wait for lazy-loaded content
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass

            # Get the rendered HTML
            html_content = page.content()

            logger.info(
                "DynamicPageFetcher: Successfully fetched %s (status: %d, size: %d bytes)",
                url,
                getattr(response, "status", -1),
                len(html_content),
            )
            return html_content.encode("utf-8")

        except Exception as e:
            logger.error("DynamicPageFetcher: Failed to fetch %s: %s", url, e)
            raise ValueError(f"Dynamic fetch failed for {url}: {str(e)}")

        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def close(self) -> None:
        """Close Playwright resources."""
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        finally:
            self._context = None

        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        finally:
            self._playwright = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ---------------------------------------------------------------------------
# Metadata Extractor
# ---------------------------------------------------------------------------

class MetadataExtractor:
    """Extracts page-level metadata like title, description, author, etc."""

    @classmethod
    def extract(cls, soup: BeautifulSoup, url: str) -> PageMetadata:
        """Extract metadata from a parsed page."""
        title = cls._extract_title(soup)
        description = cls._extract_description(soup)
        author = cls._extract_author(soup)
        publish_date = cls._extract_publish_date(soup)

        return PageMetadata(
            url=url,
            title=title,
            description=description,
            author=author,
            publish_date=publish_date,
        )

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        """Extract page title with fallbacks."""
        # Try OpenGraph title first
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        # Try Twitter title
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            return twitter_title["content"].strip()

        # Try regular title tag
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)

        # Try h1 as last resort
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        return ""

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str:
        """Extract page description."""
        # Try OpenGraph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()

        # Try Twitter description
        twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
        if twitter_desc and twitter_desc.get("content"):
            return twitter_desc["content"].strip()

        # Try meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()

        return ""

    @staticmethod
    def _extract_author(soup: BeautifulSoup) -> str:
        """Extract author information."""
        # Try meta author
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"].strip()

        # Try article author
        article_author = soup.find("meta", property="article:author")
        if article_author and article_author.get("content"):
            return article_author["content"].strip()

        return ""

    @staticmethod
    def _extract_publish_date(soup: BeautifulSoup) -> str:
        """Extract publication date."""
        for selector in DATE_META_SELECTORS:
            meta = soup.select_one(selector)
            if meta and meta.get("content"):
                return meta["content"].strip()

        return ""


# ---------------------------------------------------------------------------
# Text Extractor
# ---------------------------------------------------------------------------

class TextExtractor:
    """Extracts clean text content from HTML."""

    @classmethod
    def extract(cls, soup: BeautifulSoup) -> tuple[str, TextStats, list[str], list[str]]:
        """Extract meaningful content and compute statistics."""
        cls._remove_noise(soup)
        text, headings, paragraphs = cls._extract_structured(soup)
        stats = cls._calculate_stats(text)
        return text, stats, headings, paragraphs

    @staticmethod
    def _remove_noise(soup: BeautifulSoup) -> None:
        """Remove non-content elements from the DOM."""
        for tag in soup.find_all(NOISE_TAGS):
            tag.decompose()

        for tag in soup.find_all(True):
            if not hasattr(tag, "get"):
                continue
            attrs = " ".join(tag.get("class", [])).lower()
            tag_id = (tag.get("id") or "").lower()
            hay = f"{attrs} {tag_id}"
            if any(k in hay for k in ("nav", "menu", "footer", "header", "sidebar", "cookie", "subscribe", "breadcrumb", "promo", "advert", "ads")):
                tag.decompose()

    @staticmethod
    def _normalize_lines(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in items:
            text = re.sub(r"\s+", " ", (raw or "").strip())
            if not text:
                continue
            if len(text) < 2:
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    @classmethod
    def _extract_structured(cls, soup: BeautifulSoup) -> tuple[str, list[str], list[str]]:
        containers = [
            soup.select_one("article"),
            soup.select_one("main"),
            soup.select_one('[role="main"]'),
        ]
        root = next((c for c in containers if c is not None), None) or soup.body or soup

        headings_raw: list[str] = []
        paragraphs_raw: list[str] = []

        for h in root.find_all(["h1", "h2", "h3"]):
            headings_raw.append(h.get_text(" ", strip=True))

        for p in root.find_all("p"):
            paragraphs_raw.append(p.get_text(" ", strip=True))

        headings = cls._normalize_lines(headings_raw)
        paragraphs = cls._normalize_lines([p for p in paragraphs_raw if len(p.strip()) >= 20])

        text_parts: list[str] = []
        if headings:
            text_parts.append("\n".join(headings))
        if paragraphs:
            text_parts.append("\n\n".join(paragraphs))
        text = "\n\n".join(text_parts).strip()

        if not text:
            body = soup.find("body")
            fallback_text = body.get_text(separator=" ", strip=True) if body else ""
            text = re.sub(r"\s+", " ", fallback_text).strip()

        return text, headings, paragraphs

    @staticmethod
    def _extract_main_content(soup: BeautifulSoup) -> str:
        """Try to find the main content area, fallback to body text."""
        # Priority order for content containers
        selectors = [
            "article",
            "main",
            '[role="main"]',
            "section",
            ".content",
            ".article",
            ".post",
            ".main",
            "#content",
            "#main",
            "#article",
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(separator=" ", strip=True)
                if len(text) > 100:  # Reasonable content length
                    return text

        # Fallback: collect all paragraph text
        paragraphs = soup.find_all("p")
        if paragraphs:
            return " ".join(p.get_text(strip=True) for p in paragraphs)

        # Last resort: all body text
        body = soup.find("body")
        return body.get_text(separator=" ", strip=True) if body else ""

    @staticmethod
    def _calculate_stats(text: str) -> TextStats:
        """Compute text statistics."""
        if not text:
            return TextStats()

        words = text.split()

        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", text)
            if s.strip()
        ]

        paragraphs = [p for p in text.split("\n\n") if p.strip()]

        avg_words = (
            sum(len(s.split()) for s in sentences) / len(sentences)
            if sentences else 0.0
        )

        return TextStats(
            word_count=len(words),
            char_count=len(text),
            line_count=len(text.split("\n")),
            paragraph_count=len(paragraphs),
            sentence_count=len(sentences),
            avg_words_per_sentence=round(avg_words, 1),
        )


# ---------------------------------------------------------------------------
# Image Extractor
# ---------------------------------------------------------------------------

class ImageExtractor:
    """Discovers all <img> tags and returns normalised ImageInfo objects."""

    @classmethod
    def extract(cls, soup: BeautifulSoup, base_url: str) -> list[ImageInfo]:
        images: list[ImageInfo] = []

        for img in soup.find_all("img"):
            # Prefer data-src (lazy-loaded) over src
            src = img.get("data-src") or img.get("src")

            # Skip missing or inline data-URIs
            if not src or src.strip().startswith("data:"):
                continue

            absolute = urljoin(base_url, src.strip())

            images.append(
                ImageInfo(
                    src=absolute,
                    alt=img.get("alt", ""),
                    title=img.get("title", ""),
                    width=img.get("width"),
                    height=img.get("height"),
                )
            )

        logger.debug("Discovered %d images on %s.", len(images), base_url)
        return images


# ---------------------------------------------------------------------------
# Image Downloader
# ---------------------------------------------------------------------------

class ImageDownloader:
    """Downloads images one-by-one with configurable rate limiting."""

    def __init__(self, fetcher: PageFetcher, images_dir: str) -> None:
        self._fetcher = fetcher
        self._images_dir = images_dir

    def download_all(
        self,
        images: list[ImageInfo],
        cap: int = IMAGE_DOWNLOAD_CAP,
    ) -> list[DownloadedImage]:
        """Download up to *cap* images; return only the ones that succeeded."""
        os.makedirs(self._images_dir, exist_ok=True)
        results: list[DownloadedImage] = []

        for idx, info in enumerate(images[:cap]):
            result = self._download_one(info, idx)
            if result:
                results.append(result)
            time.sleep(IMAGE_RATE_LIMIT)

        logger.info(
            "Downloaded %d / %d images.", len(results), min(len(images), cap)
        )
        return results

    def _download_one(
        self, info: ImageInfo, index: int
    ) -> Optional[DownloadedImage]:
        try:
            content = self._fetcher.fetch_binary(info.src)
        except ValueError as exc:
            logger.warning("Skipping image %s — %s", info.src, exc)
            return None

        filename = self._safe_filename(info.src, index)
        filepath = os.path.join(self._images_dir, filename)
        ext = os.path.splitext(filename)[1].lstrip(".") or "jpeg"
        data_url = f"data:image/{ext};base64,{base64.b64encode(content).decode()}"

        try:
            with open(filepath, "wb") as fh:
                fh.write(content)
        except OSError as exc:
            logger.error("Could not write image to %s: %s", filepath, exc)
            return None

        return DownloadedImage(
            filename=filename,
            filepath=filepath,
            size_bytes=len(content),
            data_url=data_url,
            original_src=info.src,
        )

    @staticmethod
    def _safe_filename(src: str, index: int) -> str:
        """Build a safe, filesystem-friendly filename from the image URL."""
        path_part = urlparse(src).path
        basename = os.path.basename(path_part).split("?")[0]

        # Keep only alphanumeric, dots, dashes, underscores; truncate
        basename = re.sub(r"[^\w.\-]", "_", basename)[:80]

        _, ext = os.path.splitext(basename)
        if ext.lower() not in VALID_IMAGE_EXTENSIONS:
            basename += ".jpg"

        return f"image_{index:03d}_{basename}" if basename else f"image_{index:03d}.jpg"


# ---------------------------------------------------------------------------
# Storage Service
# ---------------------------------------------------------------------------

class StorageService:
    """Writes scraped artefacts to disk."""

    def __init__(self, data_dir: str, images_dir: str) -> None:
        self._data_dir = data_dir
        self._images_dir = images_dir
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

    def save_text(self, result: TextResult) -> list[str]:
        """Save a plain-text file with a header block and the scraped body."""
        filename = f"text_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(self._data_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(f"URL:       {result.url}\n")
                fh.write(f"Title:     {result.title}\n")
                fh.write(f"Scraped:   {result.timestamp}\n")
                fh.write(f"Words:     {result.stats.word_count}\n")
                fh.write(f"Sentences: {result.stats.sentence_count}\n")
                fh.write("=" * 60 + "\n\n")
                fh.write(result.text)
            logger.info("Saved text data → %s", filepath)
            return [filepath]
        except OSError as exc:
            logger.error("Failed to save text data: %s", exc)
            return []

    def save_image_manifest(self, url: str, image_result: ImageResult) -> list[str]:
        """Save a JSON manifest of image metadata and download statistics."""
        filename = f"image_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self._data_dir, filename)

        payload = {
            "url": url,
            "scraped_at": datetime.now().isoformat(),
            "statistics": {
                "total_found": image_result.total_found,
                "downloaded": image_result.downloaded,
                "total_size_mb": round(image_result.total_size_mb, 3),
            },
            "images": image_result.downloaded_images,
        }

        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            logger.info("Saved image manifest → %s", filepath)
            return [filepath]
        except OSError as exc:
            logger.error("Failed to save image manifest: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Main Service
# ---------------------------------------------------------------------------

class DataScraperService:
    """Facade that wires all components together."""

    VALID_SCRAPE_TYPES = {"text", "images", "both"}

    def __init__(
        self,
        data_dir: str = "data",
        images_dir: str = "data/images",
    ) -> None:
        self._fetcher = PageFetcher()
        self._storage = StorageService(data_dir, images_dir)
        self._downloader = ImageDownloader(self._fetcher, images_dir)
        self._dynamic_fetcher = None  # Initialized on demand

    def scrape(self, url: str, scrape_type: str = "text", use_dynamic: bool = False) -> dict:
        """Main entry point."""
        if not self._is_valid_url(url):
            return {"error": "Invalid URL format."}

        if scrape_type not in self.VALID_SCRAPE_TYPES:
            return {
                "error": (
                    f"Invalid scrape_type '{scrape_type}'. "
                    f"Valid options: {', '.join(sorted(self.VALID_SCRAPE_TYPES))}."
                )
            }

        html: bytes
        soup: BeautifulSoup

        def _fetch_with_timeout(_fetcher, _url: str, _timeout_s: int) -> bytes:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_fetcher.fetch_page, _url)
                try:
                    return future.result(timeout=_timeout_s)
                except concurrent.futures.TimeoutError:
                    raise ValueError(f"Timeout while fetching {_url} (>{_timeout_s}s)")

        try:
            fetcher = self._get_fetcher(use_dynamic)
            fetcher_type = "Dynamic" if use_dynamic else "Static"
            logger.info("DataScraperService: Using %s fetcher for %s", fetcher_type, url)

            fetch_timeout = 45 if use_dynamic else REQUEST_TIMEOUT + 5
            html = _fetch_with_timeout(fetcher, url, fetch_timeout)
            soup = BeautifulSoup(html, "html.parser")
        except ValueError as exc:
            logger.error("Page fetch failed for %s: %s", url, exc)
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected fetch error for %s", url)
            return {"error": f"Failed to fetch page: {exc}"}

        if not use_dynamic and scrape_type in {"text", "both"}:
            try:
                text_preview, stats_preview, _, _ = TextExtractor.extract(deepcopy(soup))
                is_thin = (stats_preview.word_count < 80) or (len(text_preview.strip()) < 800)
                has_many_scripts = len(soup.find_all("script")) > 25
                if is_thin and has_many_scripts:
                    logger.info("Static extraction seems thin; retrying with dynamic fetch for %s", url)
                    dyn = self._get_fetcher(True)
                    html = _fetch_with_timeout(dyn, url, 45)
                    soup = BeautifulSoup(html, "html.parser")
            except ImportError as exc:
                logger.warning("Dynamic fetch unavailable for %s: %s", url, exc)
            except Exception as exc:
                logger.warning("Dynamic fallback failed for %s: %s", url, exc)

        if scrape_type == "text":
            return self._run_text_pipeline(url, soup)

        if scrape_type == "images":
            return self._run_image_pipeline(url, soup)

        # "both" — run text on a deep-copy so noise removal doesn't affect images
        text_result = self._run_text_pipeline(url, deepcopy(soup))
        image_result = self._run_image_pipeline(url, soup)

        return {
            "success": True,
            "text_data": text_result,
            "image_data": image_result,
            "timestamp": datetime.now().isoformat(),
        }

    def _run_text_pipeline(self, url: str, soup: BeautifulSoup) -> dict:
        """Extract text → compute stats → persist → return response dict."""
        try:
            metadata = MetadataExtractor.extract(soup, url)
            text, stats, headings, paragraphs = TextExtractor.extract(soup)

            result = TextResult(
                url=url,
                title=metadata.title,
                text=text,
                stats=stats,
                headings=headings,
                paragraphs=paragraphs,
            )

            if text.strip():
                result.saved_files = self._storage.save_text(result)
            else:
                logger.warning("No text content extracted from %s.", url)

            return {
                "type": "text",
                "success": True,
                "content": result.to_dict(),
                "saved_files": result.saved_files,
                "timestamp": result.timestamp,
            }

        except Exception:
            logger.exception("Text pipeline failed for %s.", url)
            return {"error": "Text scraping failed due to an internal error."}

    def _run_image_pipeline(self, url: str, soup: BeautifulSoup) -> dict:
        """Discover images → download → persist manifest → return response dict."""
        try:
            images = ImageExtractor.extract(soup, url)
            downloaded = self._downloader.download_all(images)

            total_bytes = sum(img.size_bytes for img in downloaded)
            result = ImageResult(
                total_found=len(images),
                downloaded=len(downloaded),
                total_size_mb=total_bytes / (1024 * 1024),
                downloaded_images=[img.to_dict() for img in downloaded],
            )

            result.saved_files = self._storage.save_image_manifest(url, result)

            return {
                "type": "images",
                "success": True,
                "images": result.to_dict(),
                "saved_files": result.saved_files,
                "timestamp": result.timestamp,
            }

        except Exception:
            logger.exception("Image pipeline failed for %s.", url)
            return {"error": "Image scraping failed due to an internal error."}

    def _get_fetcher(self, use_dynamic: bool = False):
        """Get appropriate fetcher based on use_dynamic flag."""
        if use_dynamic:
            if self._dynamic_fetcher is None:
                self._dynamic_fetcher = DynamicPageFetcher()
            return self._dynamic_fetcher
        else:
            return self._fetcher

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc)
        except Exception:
            return False
