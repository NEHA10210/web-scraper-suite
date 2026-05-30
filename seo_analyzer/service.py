"""
SEO Analyzer Service Layer
===========================
Analyzes web pages for SEO factors: meta tags, headings, links,
images, content quality, technical signals, and performance.

Architecture:
    - SEOAnalyzerService     : Facade — the only class blueprints should import
    - PageFetcher            : HTTP fetching with retry + backoff
    - MetaTagAnalyzer        : Title, description, keywords, OG, Twitter Cards
    - HeadingAnalyzer        : Heading structure, hierarchy validation
    - LinkAnalyzer           : Internal / external / broken link detection
    - ImageAnalyzer          : Alt-text coverage, lazy-src handling
    - ContentAnalyzer        : Word count, keyword density, readability
    - TechnicalAnalyzer      : HTTPS, schema.org, mobile-friendliness
    - PerformanceAnalyzer    : Load time, page size, grading
    - SEOScorer              : Aggregates component scores → overall score
    - RecommendationEngine   : Derives actionable recommendations from scores
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
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

REQUEST_TIMEOUT      = 12       # seconds — page fetch
LINK_CHECK_TIMEOUT   = 5        # seconds — HEAD request per link
MAX_RETRIES          = 3
RETRY_BACKOFF        = 2.0      # exponential-backoff multiplier

LINK_CHECK_CAP       = 10       # max links whose status is verified live
INTERNAL_LINK_CAP    = 50       # max internal links returned in payload
EXTERNAL_LINK_CAP    = 50       # max external links returned in payload
BROKEN_LINK_CAP      = 5        # max broken links shown in payload
IMAGE_CAP            = 20       # max images returned in detail payload
TOP_KEYWORD_COUNT    = 5        # number of top keywords to surface

TITLE_MIN            = 30
TITLE_MAX            = 60
DESC_MIN             = 120
DESC_MAX             = 160
MIN_WORD_COUNT       = 300
READABILITY_BASELINE = 15       # avg words/sentence considered "readable"

NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside"]

STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "through", "during",
    "before", "after", "above", "below", "between", "among", "this",
    "that", "these", "those", "i", "you", "he", "she", "it", "we",
    "they", "what", "which", "who", "whom", "am", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "must",
    "can", "shall", "a", "an", "as", "if", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "now", "also", "here", "there",
    "then", "again", "further", "once",
})

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

OG_TAGS      = ("og:title", "og:description", "og:image", "og:url")
TWITTER_TAGS = ("twitter:card", "twitter:title", "twitter:description", "twitter:image")
DATE_SELECTORS = (
    'meta[property="article:published_time"]',
    'meta[name="date"]',
    'meta[name="publish_date"]',
    'meta[property="datePublished"]',
)


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------

@dataclass
class BasicInfo:
    title: Optional[str]
    title_length: int
    description: Optional[str]
    description_length: int
    keywords: Optional[str]
    language: Optional[str]
    canonical_url: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetaTagInfo:
    title: Optional[str]
    description: Optional[str]
    keywords: Optional[str]
    all_tags: list[dict]
    missing_essential: list[str]
    has_description: bool
    has_viewport: bool
    has_robots: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HeadingInfo:
    h1: list[dict] = field(default_factory=list)
    h2: list[dict] = field(default_factory=list)
    h3: list[dict] = field(default_factory=list)
    h4: list[dict] = field(default_factory=list)
    h5: list[dict] = field(default_factory=list)
    h6: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LinkInfo:
    internal_count: int
    external_count: int
    total_count: int
    broken_count: int
    broken_links: list[dict]
    internal_links: list[dict]
    external_links: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImageInfo:
    total_count: int
    with_alt_count: int
    without_alt_count: int
    alt_coverage: float
    images: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContentInfo:
    word_count: int
    sentence_count: int
    avg_words_per_sentence: float
    top_keywords: list[dict]
    has_enough_content: bool
    readability_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TechnicalInfo:
    status_code: int
    response_time: float
    content_type: str
    content_length: int
    has_schema: bool
    has_open_graph: bool
    has_twitter_cards: bool
    uses_https: bool
    is_mobile_friendly: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerformanceInfo:
    load_time: float
    load_grade: str
    size_kb: float
    size_mb: float
    is_fast: bool
    size_optimized: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SEOScore:
    overall_score: int
    technical_score: int
    content_score: int
    performance_score: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recommendation:
    type: str       # "critical" | "warning" | "info"
    category: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Page Fetcher
# ---------------------------------------------------------------------------

class PageFetcher:
    """Handles all outbound HTTP with retry + exponential backoff."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)

    def fetch(self, url: str, method: str = "GET", timeout: int = REQUEST_TIMEOUT) -> requests.Response:
        """
        Execute *method* for *url* and return the Response.
        Raises ``ValueError`` on permanent failure after all retries.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.request(method, url, timeout=timeout, allow_redirects=True)
                resp.raise_for_status()
                return resp
            except requests.exceptions.HTTPError as exc:
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

    def head(self, url: str) -> Optional[int]:
        """
        Return the HTTP status code for *url* via HEAD, or None on error.
        Intentionally swallows exceptions — used only for link-checking.
        """
        try:
            resp = self._session.head(url, timeout=LINK_CHECK_TIMEOUT, allow_redirects=True)
            return resp.status_code
        except Exception as exc:
            logger.debug("HEAD check failed for %s: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _safe_text(element) -> str:
    """Extract stripped text from a BS4 element without calling get_text()."""
    if not element:
        return ""
    try:
        return " ".join(str(s) for s in element.stripped_strings).strip()
    except Exception:
        return str(getattr(element, "string", "") or "").strip()


# ---------------------------------------------------------------------------
# Meta Tag Analyzer
# ---------------------------------------------------------------------------

class MetaTagAnalyzer:
    """Analyses all <meta> tags and social-sharing signals."""

    ESSENTIAL_META = ("description", "keywords", "viewport", "robots")

    @classmethod
    def basic_info(cls, soup: BeautifulSoup) -> BasicInfo:
        title       = cls._title(soup)
        description = cls._meta_attr(soup, "name", "description")
        return BasicInfo(
            title=title,
            title_length=len(title) if title else 0,
            description=description,
            description_length=len(description) if description else 0,
            keywords=cls._meta_attr(soup, "name", "keywords"),
            language=cls._language(soup),
            canonical_url=cls._canonical(soup),
        )

    @classmethod
    def full_analysis(cls, soup: BeautifulSoup) -> MetaTagInfo:
        all_tags = [
            {
                "name": (
                    m.get("name") or m.get("property") or m.get("http-equiv")
                ),
                "content": m.get("content"),
                "charset": m.get("charset"),
            }
            for m in soup.find_all("meta")
        ]

        tag_names = {t["name"] for t in all_tags if t["name"]}
        missing   = [t for t in cls.ESSENTIAL_META if t not in tag_names]

        return MetaTagInfo(
            title=cls._title(soup),
            description=cls._meta_attr(soup, "name", "description"),
            keywords=cls._meta_attr(soup, "name", "keywords"),
            all_tags=all_tags,
            missing_essential=missing,
            has_description="description" in tag_names,
            has_viewport="viewport" in tag_names,
            has_robots="robots" in tag_names,
        )

    @classmethod
    def has_open_graph(cls, soup: BeautifulSoup) -> bool:
        found = sum(
            1 for tag in OG_TAGS
            if (t := soup.find("meta", attrs={"property": tag})) and t.get("content")
        )
        return found >= 2

    @classmethod
    def has_twitter_cards(cls, soup: BeautifulSoup) -> bool:
        found = sum(
            1 for tag in TWITTER_TAGS
            if (t := soup.find("meta", attrs={"name": tag})) and t.get("content")
        )
        return found >= 2

    @classmethod
    def is_mobile_friendly(cls, soup: BeautifulSoup) -> bool:
        return bool(
            soup.find("meta", attrs={"name": "viewport"})
            or soup.find("meta", attrs={"name": "mobile-web-app-capable"})
            or soup.find("meta", attrs={"name": "apple-mobile-web-app-capable"})
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _title(soup: BeautifulSoup) -> Optional[str]:
        tag = soup.find("title")
        text = _safe_text(tag) if tag else None
        return text or None

    @staticmethod
    def _meta_attr(soup: BeautifulSoup, attr: str, value: str) -> Optional[str]:
        tag = soup.find("meta", attrs={attr: value})
        content = tag.get("content") if tag else None
        return content or None

    @staticmethod
    def _language(soup: BeautifulSoup) -> Optional[str]:
        html = soup.find("html")
        return html.get("lang") if html else None

    @staticmethod
    def _canonical(soup: BeautifulSoup) -> Optional[str]:
        link = soup.find("link", attrs={"rel": "canonical"})
        return link.get("href") if link else None


# ---------------------------------------------------------------------------
# Heading Analyzer
# ---------------------------------------------------------------------------

class HeadingAnalyzer:
    """Extracts and validates the heading hierarchy (H1–H6)."""

    @classmethod
    def analyze(cls, soup: BeautifulSoup) -> HeadingInfo:
        info = HeadingInfo()
        level_map = {f"h{i}": getattr(info, f"h{i}") for i in range(1, 7)}

        for level, bucket in level_map.items():
            for tag in soup.find_all(level):
                text = _safe_text(tag)
                bucket.append({"text": text, "length": len(text)})

        return info

    @staticmethod
    def hierarchy_is_valid(soup: BeautifulSoup) -> bool:
        """Return False if any heading level skips more than one step."""
        levels = [
            int(tag.name[1])
            for i in range(1, 7)
            for tag in soup.find_all(f"h{i}")
        ]
        if len(levels) < 2:
            return True
        return all(levels[i] - levels[i - 1] <= 1 for i in range(1, len(levels)))


# ---------------------------------------------------------------------------
# Link Analyzer
# ---------------------------------------------------------------------------

class LinkAnalyzer:
    """Classifies and optionally verifies all <a href> links on the page."""

    def __init__(self, fetcher: PageFetcher) -> None:
        self._fetcher = fetcher

    def analyze(self, soup: BeautifulSoup, base_url: str) -> LinkInfo:
        base_domain    = urlparse(base_url).netloc
        internal_links: list[dict] = []
        external_links: list[dict] = []
        broken_links:   list[dict] = []
        checked         = 0

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()

            # Skip anchors, javascript pseudo-links, and mailto
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            absolute = urljoin(base_url, href)
            is_external = urlparse(absolute).netloc != base_domain

            link = {
                "url":         absolute,
                "text":        _safe_text(a),
                "is_external": is_external,
                "status_code": None,
                "is_broken":   False,
            }

            # Live-check only the first LINK_CHECK_CAP links
            if checked < LINK_CHECK_CAP:
                status = self._fetcher.head(absolute)
                link["status_code"] = status or 0
                link["is_broken"]   = status is None or status not in range(200, 400)
                checked += 1

            if is_external:
                external_links.append(link)
            else:
                internal_links.append(link)

            if link["is_broken"]:
                broken_links.append(link)

        return LinkInfo(
            internal_count=len(internal_links),
            external_count=len(external_links),
            total_count=len(internal_links) + len(external_links),
            broken_count=len(broken_links),
            broken_links=broken_links[:BROKEN_LINK_CAP],
            internal_links=internal_links[:INTERNAL_LINK_CAP],
            external_links=external_links[:EXTERNAL_LINK_CAP],
        )


# ---------------------------------------------------------------------------
# Image Analyzer
# ---------------------------------------------------------------------------

class ImageAnalyzer:
    """Audits every <img> tag for alt-text coverage."""

    @classmethod
    def analyze(cls, soup: BeautifulSoup, base_url: str) -> ImageInfo:
        images:           list[dict] = []
        without_alt_count = 0

        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy")
                or (img.get("srcset", "").split()[0] if img.get("srcset") else None)
            )

            if not src or src.strip().startswith("data:"):
                continue

            absolute = urljoin(base_url, src.strip())
            alt      = img.get("alt", "").strip()
            has_alt  = bool(alt)

            images.append({
                "src":        absolute,
                "alt":        alt,
                "has_alt":    has_alt,
                "alt_length": len(alt),
            })

            if not has_alt:
                without_alt_count += 1

        total         = len(images)
        with_alt      = total - without_alt_count
        alt_coverage  = round(with_alt / total * 100, 1) if total else 0.0

        return ImageInfo(
            total_count=total,
            with_alt_count=with_alt,
            without_alt_count=without_alt_count,
            alt_coverage=alt_coverage,
            images=images[:IMAGE_CAP],
        )


# ---------------------------------------------------------------------------
# Content Analyzer
# ---------------------------------------------------------------------------

class ContentAnalyzer:
    """
    Extracts clean body text (after removing noise tags) and computes
    word count, keyword density, and a simple readability score.

    NOTE: Decomposes noise tags in-place on the passed soup copy.
    """

    @classmethod
    def analyze(cls, soup: BeautifulSoup) -> ContentInfo:
        cls._strip_noise(soup)
        text  = _safe_text(soup)
        words = text.split()

        word_count      = len(words)
        top_keywords    = cls._top_keywords(words)
        sentences       = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        sentence_count  = len(sentences)
        avg_wps         = word_count / sentence_count if sentence_count else 0.0
        # Simple Flesch-inspired readability proxy capped 0–100
        readability     = float(min(100, max(0, 100 - (avg_wps - READABILITY_BASELINE) * 2)))

        return ContentInfo(
            word_count=word_count,
            sentence_count=sentence_count,
            avg_words_per_sentence=round(avg_wps, 1),
            top_keywords=top_keywords[:TOP_KEYWORD_COUNT],
            has_enough_content=word_count >= MIN_WORD_COUNT,
            readability_score=round(readability, 1),
        )

    @staticmethod
    def _strip_noise(soup: BeautifulSoup) -> None:
        for tag in soup(NOISE_TAGS):
            tag.decompose()

    @staticmethod
    def _top_keywords(words: list[str]) -> list[dict]:
        cleaned = [
            w.lower().strip('.,!?;:"()[]{}')
            for w in words
            if len(w.strip('.,!?;:"()[]{}')) > 3
            and w.lower().strip('.,!?;:"()[]{}') not in STOPWORDS
        ]
        total   = len(cleaned)
        return [
            {
                "keyword":   word,
                "frequency": freq,
                "density":   round(freq / total * 100, 2) if total else 0.0,
            }
            for word, freq in Counter(cleaned).most_common(10)
        ]


# ---------------------------------------------------------------------------
# Technical Analyzer
# ---------------------------------------------------------------------------

class TechnicalAnalyzer:
    """Inspects technical SEO signals from the HTTP response and the DOM."""

    @classmethod
    def analyze(cls, soup: BeautifulSoup, response: requests.Response) -> TechnicalInfo:
        return TechnicalInfo(
            status_code=response.status_code,
            response_time=round(response.elapsed.total_seconds(), 3),
            content_type=response.headers.get("content-type", ""),
            content_length=len(response.content),
            has_schema=bool(soup.find_all(attrs={"type": "application/ld+json"})),
            has_open_graph=MetaTagAnalyzer.has_open_graph(soup),
            has_twitter_cards=MetaTagAnalyzer.has_twitter_cards(soup),
            uses_https=response.url.startswith("https://"),
            is_mobile_friendly=MetaTagAnalyzer.is_mobile_friendly(soup),
        )


# ---------------------------------------------------------------------------
# Performance Analyzer
# ---------------------------------------------------------------------------

class PerformanceAnalyzer:
    """
    Derives basic performance metrics from the HTTP response object.
    These are proxy metrics — true field performance requires a headless
    browser (Lighthouse / Playwright).
    """

    @classmethod
    def analyze(cls, response: requests.Response) -> PerformanceInfo:
        load_time    = round(response.elapsed.total_seconds(), 3)
        size_bytes   = len(response.content)
        size_kb      = size_bytes / 1024
        size_mb      = size_kb / 1024

        if load_time < 1:
            grade = "A"
        elif load_time < 3:
            grade = "B"
        else:
            grade = "C"

        return PerformanceInfo(
            load_time=load_time,
            load_grade=grade,
            size_kb=round(size_kb, 2),
            size_mb=round(size_mb, 4),
            is_fast=load_time < 2.0,
            size_optimized=size_bytes < 1_048_576,   # < 1 MB
        )


# ---------------------------------------------------------------------------
# SEO Scorer
# ---------------------------------------------------------------------------

class SEOScorer:
    """
    Aggregates component-level scores into a 0–100 overall SEO score.

    Scoring breakdown (100 pts total):
        Technical  — 40 pts  (title, description, keywords, headings)
        Content    — 30 pts  (word count, image alt coverage)
        Performance— 30 pts  (load time, page size, status code)
    """

    @staticmethod
    def score(
        basic:       BasicInfo,
        meta:        MetaTagInfo,
        headings:    HeadingInfo,
        images:      ImageInfo,
        content:     ContentInfo,
        technical:   TechnicalInfo,
        performance: PerformanceInfo,
    ) -> SEOScore:
        tech = content_pts = perf = 0

        # ── Title (15 pts) ──────────────────────────────────────────────
        if basic.title:
            pts = 15 if TITLE_MIN <= basic.title_length <= TITLE_MAX else 10
            tech += pts

        # ── Meta description (10 pts) ───────────────────────────────────
        if basic.description:
            pts = 10 if DESC_MIN <= basic.description_length <= DESC_MAX else 5
            tech += pts

        # ── Meta keywords (5 pts — optional) ───────────────────────────
        if meta.keywords:
            tech += 5

        # ── Heading structure (10 pts) ──────────────────────────────────
        if len(headings.h1) == 1:
            tech += 5
        if headings.h2:
            tech += 5

        # ── Word count (15 pts) ─────────────────────────────────────────
        if content.word_count >= 300:
            content_pts += 15
        elif content.word_count >= 100:
            content_pts += 10
        elif content.word_count > 0:
            content_pts += 5

        # ── Image alt coverage (15 pts) ─────────────────────────────────
        if images.total_count > 0:
            cov = images.alt_coverage
            if cov >= 80:
                content_pts += 15
            elif cov >= 50:
                content_pts += 10
            elif cov > 0:
                content_pts += 5

        # ── Load time (15 pts) ──────────────────────────────────────────
        lt = performance.load_time
        if lt < 1:
            perf += 15
        elif lt < 3:
            perf += 10
        elif lt < 5:
            perf += 5

        # ── Page size (10 pts) ──────────────────────────────────────────
        if performance.size_mb < 1:
            perf += 10
        elif performance.size_mb < 2:
            perf += 5

        # ── Status code (5 pts) ─────────────────────────────────────────
        if technical.status_code == 200:
            perf += 5

        overall = min(tech + content_pts + perf, 100)

        return SEOScore(
            overall_score=overall,
            technical_score=min(tech, 40),
            content_score=min(content_pts, 30),
            performance_score=min(perf, 30),
        )


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """
    Produces an ordered list of SEO recommendations from analysed data.
    Severity levels: ``critical`` > ``warning`` > ``info``.
    """

    @classmethod
    def generate(
        cls,
        basic:       BasicInfo,
        headings:    HeadingInfo,
        images:      ImageInfo,
        content:     ContentInfo,
        links:       LinkInfo,
        technical:   TechnicalInfo,
        performance: PerformanceInfo,
    ) -> list[dict]:
        recs: list[Recommendation] = []

        cls._title_recs(recs, basic)
        cls._description_recs(recs, basic)
        cls._heading_recs(recs, headings)
        cls._image_recs(recs, images)
        cls._content_recs(recs, content)
        cls._link_recs(recs, links)
        cls._performance_recs(recs, performance)
        cls._technical_recs(recs, technical)

        # critical first, then warning, then info
        priority = {"critical": 0, "warning": 1, "info": 2}
        recs.sort(key=lambda r: priority.get(r.type, 3))

        return [r.to_dict() for r in recs]

    # ------------------------------------------------------------------
    # Private helpers — one per concern
    # ------------------------------------------------------------------

    @staticmethod
    def _title_recs(recs: list, basic: BasicInfo) -> None:
        if not basic.title:
            recs.append(Recommendation("critical", "title", "Add a page title for better SEO."))
        elif basic.title_length < TITLE_MIN:
            recs.append(Recommendation(
                "warning", "title",
                f"Title is too short ({basic.title_length} chars). "
                f"Aim for {TITLE_MIN}–{TITLE_MAX} characters.",
            ))
        elif basic.title_length > TITLE_MAX:
            recs.append(Recommendation(
                "warning", "title",
                f"Title is too long ({basic.title_length} chars). "
                f"Aim for {TITLE_MIN}–{TITLE_MAX} characters.",
            ))

    @staticmethod
    def _description_recs(recs: list, basic: BasicInfo) -> None:
        if not basic.description:
            recs.append(Recommendation(
                "critical", "meta",
                "Add a meta description to improve search-engine snippets.",
            ))
        elif basic.description_length < DESC_MIN:
            recs.append(Recommendation(
                "warning", "meta",
                f"Meta description is too short ({basic.description_length} chars). "
                f"Aim for {DESC_MIN}–{DESC_MAX} characters.",
            ))
        elif basic.description_length > DESC_MAX:
            recs.append(Recommendation(
                "warning", "meta",
                f"Meta description is too long ({basic.description_length} chars). "
                f"Aim for {DESC_MIN}–{DESC_MAX} characters.",
            ))

    @staticmethod
    def _heading_recs(recs: list, headings: HeadingInfo) -> None:
        h1 = len(headings.h1)
        if h1 == 0:
            recs.append(Recommendation(
                "critical", "headings",
                "Add an H1 tag to define the page's primary topic.",
            ))
        elif h1 > 1:
            recs.append(Recommendation(
                "warning", "headings",
                f"Found {h1} H1 tags — use exactly one H1 per page.",
            ))

        if not headings.h2:
            recs.append(Recommendation(
                "warning", "headings",
                "Add H2 tags to structure your content into sections.",
            ))

    @staticmethod
    def _image_recs(recs: list, images: ImageInfo) -> None:
        missing = images.without_alt_count
        if missing > 0:
            recs.append(Recommendation(
                "warning", "images",
                f"Add alt text to {missing} image(s) for accessibility and SEO.",
            ))

    @staticmethod
    def _content_recs(recs: list, content: ContentInfo) -> None:
        if content.word_count < MIN_WORD_COUNT:
            recs.append(Recommendation(
                "warning", "content",
                f"Content is thin ({content.word_count} words). "
                f"Aim for at least {MIN_WORD_COUNT} words.",
            ))

        if content.readability_score < 60:
            recs.append(Recommendation(
                "warning", "content",
                f"Readability score is low ({content.readability_score}/100). "
                "Use shorter sentences and simpler vocabulary.",
            ))

    @staticmethod
    def _link_recs(recs: list, links: LinkInfo) -> None:
        if links.internal_count == 0:
            recs.append(Recommendation(
                "warning", "links",
                "Add internal links to improve site navigation and crawlability.",
            ))

        if links.external_count == 0:
            recs.append(Recommendation(
                "info", "links",
                "Consider linking to authoritative external sources.",
            ))

        if links.broken_count > 0:
            recs.append(Recommendation(
                "critical", "links",
                f"Found {links.broken_count} broken link(s). "
                "Fix them to improve user experience and crawl health.",
            ))

    @staticmethod
    def _performance_recs(recs: list, performance: PerformanceInfo) -> None:
        lt = performance.load_time
        if lt > 3:
            recs.append(Recommendation(
                "warning", "performance",
                f"Page load time is slow ({lt:.2f}s). "
                "Optimise images and reduce render-blocking resources.",
            ))
        elif lt > 1:
            recs.append(Recommendation(
                "info", "performance",
                f"Page load time could be improved ({lt:.2f}s). Aim for under 1 second.",
            ))

    @staticmethod
    def _technical_recs(recs: list, technical: TechnicalInfo) -> None:
        if not technical.uses_https:
            recs.append(Recommendation(
                "critical", "technical",
                "Serve the page over HTTPS — required for security and search ranking.",
            ))

        if not technical.is_mobile_friendly:
            recs.append(Recommendation(
                "warning", "technical",
                "Add a viewport meta tag to ensure a good mobile experience.",
            ))

        if not technical.has_schema:
            recs.append(Recommendation(
                "info", "technical",
                "Add schema.org JSON-LD markup to enable rich results.",
            ))

        if not technical.has_open_graph:
            recs.append(Recommendation(
                "info", "technical",
                "Add Open Graph tags to improve social-sharing previews.",
            ))


# ---------------------------------------------------------------------------
# Main Service  (the only class blueprints should import)
# ---------------------------------------------------------------------------

class SEOAnalyzerService:
    """
    Facade that wires PageFetcher, all analyzers, SEOScorer, and
    RecommendationEngine together.

    Usage::

        service = SEOAnalyzerService()
        result  = service.analyze(url)
        # result is always a dict; check for 'error' key on failure
    """

    def __init__(self) -> None:
        self._fetcher      = PageFetcher()
        self._link_analyzer = LinkAnalyzer(self._fetcher)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, url: str) -> dict:
        """
        Perform a full SEO analysis of *url*.
        Always returns a dict — callers must check for ``"error"`` key.
        """
        if not self._is_valid_url(url):
            return {"error": "Invalid URL format."}

        # ── Fetch ──────────────────────────────────────────────────────
        try:
            response = self._fetcher.fetch(url)
        except ValueError as exc:
            logger.error("Page fetch failed for %s: %s", url, exc)
            return {"error": str(exc)}

        soup = BeautifulSoup(response.content, "html.parser")

        # ── Content analysis runs on a copy (decompose mutates the tree) ──
        from copy import deepcopy
        content_soup = deepcopy(soup)

        # ── Run all analyzers ──────────────────────────────────────────
        basic       = MetaTagAnalyzer.basic_info(soup)
        meta        = MetaTagAnalyzer.full_analysis(soup)
        headings    = HeadingAnalyzer.analyze(soup)
        links       = self._link_analyzer.analyze(soup, url)
        images      = ImageAnalyzer.analyze(soup, url)
        content     = ContentAnalyzer.analyze(content_soup)   # uses copy
        technical   = TechnicalAnalyzer.analyze(soup, response)
        performance = PerformanceAnalyzer.analyze(response)

        # ── Score + recommendations ────────────────────────────────────
        seo_score       = SEOScorer.score(basic, meta, headings, images, content, technical, performance)
        recommendations = RecommendationEngine.generate(
            basic, headings, images, content, links, technical, performance
        )

        return {
            "url":             url,
            "timestamp":       datetime.now().isoformat(),
            "basic_info":      basic.to_dict(),
            "meta_tags":       meta.to_dict(),
            "headings":        headings.to_dict(),
            "links":           links.to_dict(),
            "images":          images.to_dict(),
            "content":         content.to_dict(),
            "technical":       technical.to_dict(),
            "performance":     performance.to_dict(),
            "seo_score":       seo_score.to_dict(),
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            p = urlparse(url)
            return bool(p.scheme and p.netloc)
        except Exception:
            return False