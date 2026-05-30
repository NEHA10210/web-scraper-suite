"""
Improved Data Scraper Service with all fixes applied
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Constants
REQUEST_TIMEOUT = 15
IMAGE_TIMEOUT = 10
MAX_RETRIES = 3
IMAGE_DOWNLOAD_CAP = 20
IMAGE_RATE_LIMIT = 0.5
VALID_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

# Data classes
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

class MetadataExtractor:
    """Extracts page metadata."""
    
    @staticmethod
    def extract(soup: BeautifulSoup, url: str) -> dict:
        """Extract metadata from page."""
        title = MetadataExtractor._extract_title(soup)
        description = MetadataExtractor._extract_description(soup)
        author = MetadataExtractor._extract_author(soup)
        
        return {
            "url": url,
            "title": title,
            "description": description,
            "author": author,
            "scraped_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        """Extract page title."""
        # Try OpenGraph title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        
        # Try Twitter title
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            return twitter_title["content"].strip()
        
        # Try regular title
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        
        return ""
    
    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str:
        """Extract page description."""
        # Try OpenGraph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()
        
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
        
        return ""

class ImageExtractor:
    """Extracts image information."""
    
    @staticmethod
    def extract(soup: BeautifulSoup, base_url: str) -> list[ImageInfo]:
        """Extract all images from page."""
        images = []
        
        for img in soup.find_all("img"):
            # Prefer data-src for lazy-loaded images
            src = img.get("data-src") or img.get("src")
            
            if not src or src.strip().startswith("data:"):
                continue
            
            absolute = urljoin(base_url, src.strip())
            
            images.append(ImageInfo(
                src=absolute,
                alt=img.get("alt", ""),
                title=img.get("title", ""),
                width=img.get("width"),
                height=img.get("height"),
            ))
        
        return images

class ImageDownloader:
    """Downloads images."""
    
    def __init__(self, fetcher, images_dir: str):
        self._fetcher = fetcher
        self._images_dir = images_dir
    
    def download_all(self, images: list[ImageInfo], cap: int = IMAGE_DOWNLOAD_CAP) -> list[DownloadedImage]:
        """Download images."""
        os.makedirs(self._images_dir, exist_ok=True)
        results = []
        
        for idx, info in enumerate(images[:cap]):
            result = self._download_one(info, idx)
            if result:
                results.append(result)
            time.sleep(IMAGE_RATE_LIMIT)
        
        return results
    
    def _download_one(self, info: ImageInfo, index: int) -> Optional[DownloadedImage]:
        """Download single image."""
        try:
            content = self._fetcher.fetch_binary(info.src)
        except ValueError:
            return None
        
        filename = self._safe_filename(info.src, index)
        filepath = os.path.join(self._images_dir, filename)
        ext = os.path.splitext(filename)[1].lstrip(".") or "jpeg"
        data_url = f"data:image/{ext};base64,{base64.b64encode(content).decode()}"
        
        try:
            with open(filepath, "wb") as f:
                f.write(content)
        except OSError:
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
        """Generate safe filename."""
        path_part = urlparse(src).path
        basename = os.path.basename(path_part).split("?")[0]
        
        basename = re.sub(r"[^\w.\-]", "_", basename)[:80]
        
        _, ext = os.path.splitext(basename)
        if ext.lower() not in VALID_IMAGE_EXTENSIONS:
            basename += ".jpg"
        
        return f"image_{index:03d}_{basename}" if basename else f"image_{index:03d}.jpg"

class StorageService:
    """Saves scraped data."""
    
    def __init__(self, data_dir: str, images_dir: str):
        self._data_dir = data_dir
        self._images_dir = images_dir
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)
    
    def save_text(self, result: TextResult) -> list[str]:
        """Save text data."""
        filename = f"text_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(self._data_dir, filename)
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"URL: {result.url}\n")
                f.write(f"Title: {result.title}\n")
                f.write(f"Scraped: {result.timestamp}\n")
                f.write(f"Words: {result.stats.word_count}\n")
                f.write("=" * 60 + "\n\n")
                f.write(result.text)
            return [filepath]
        except OSError:
            return []
    
    def save_image_manifest(self, url: str, image_result: ImageResult) -> list[str]:
        """Save image manifest."""
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
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return [filepath]
        except OSError:
            return []

class ImprovedDataScraperService:
    """Improved Data Scraper Service with all fixes."""
    
    VALID_SCRAPE_TYPES = {"text", "images", "both"}
    
    def __init__(self, data_dir: str = "data", images_dir: str = "data/images", 
                 strict_mode: bool = False):
        self._fetcher = self._create_fetcher()
        self._storage = StorageService(data_dir, images_dir)
        self._downloader = ImageDownloader(self._fetcher, images_dir)
        self._text_extractor = None
        self._strict_mode = strict_mode
    
    def _create_fetcher(self):
        """Create improved page fetcher."""
        from .improved_page_fetcher import ImprovedPageFetcher
        return ImprovedPageFetcher()
    
    def _get_text_extractor(self):
        """Get or create text extractor."""
        if self._text_extractor is None:
            from .improved_text_extractor import ImprovedTextExtractor
            self._text_extractor = ImprovedTextExtractor(
                min_word_threshold=10,
                strict_mode=self._strict_mode
            )
        return self._text_extractor
    
    def scrape(self, url: str, scrape_type: str = "text", use_dynamic: bool = False) -> dict:
        """
        Main scraping method with consistent API response format.
        
        Always returns:
        {
            success: bool,
            type: "text" | "images" | "both",
            content: {} | null,
            error: str | null
        }
        """
        # Validate URL
        if not self._is_valid_url(url):
            return {
                "success": False,
                "type": scrape_type,
                "content": None,
                "error": "Invalid URL format"
            }
        
        # Validate scrape type
        if scrape_type not in self.VALID_SCRAPE_TYPES:
            return {
                "success": False,
                "type": scrape_type,
                "content": None,
                "error": f"Invalid scrape_type '{scrape_type}'. Valid options: {', '.join(sorted(self.VALID_SCRAPE_TYPES))}"
            }
        
        logger.info("ImprovedDataScraperService: Scraping %s (type=%s, dynamic=%s)", url, scrape_type, use_dynamic)
        
        try:
            # Fetch page
            html = self._fetcher.fetch_page(url, use_dynamic=use_dynamic)
            soup = BeautifulSoup(html, "html.parser")
            
            # Process based on scrape type
            if scrape_type == "text":
                return self._scrape_text(url, soup)
            elif scrape_type == "images":
                return self._scrape_images(url, soup)
            else:  # both
                return self._scrape_both(url, soup)
                
        except Exception as e:
            logger.exception("ImprovedDataScraperService: Scraping failed for %s", url)
            return {
                "success": False,
                "type": scrape_type,
                "content": None,
                "error": f"Scraping failed: {str(e)}"
            }
    
    def _scrape_text(self, url: str, soup: BeautifulSoup) -> dict:
        """Scrape text content."""
        try:
            # Extract metadata
            metadata = MetadataExtractor.extract(soup, url)
            
            # Extract text using improved extractor
            extractor = self._get_text_extractor()
            text, extraction_info = extractor.extract(soup)
            
            # Calculate stats
            stats = self._calculate_stats(text)
            
            # Create result
            result = TextResult(
                url=url,
                title=metadata["title"],
                text=text,
                stats=stats
            )
            
            # Save if meaningful content
            saved_files = []
            if text.strip() and stats.word_count >= 5:
                saved_files = self._storage.save_text(result)
            
            # Log extraction info
            logger.info("ImprovedDataScraperService: Text extraction complete - strategy: %s, words: %d", 
                       extraction_info.get("strategy", "unknown"), stats.word_count)
            
            return {
                "success": True,
                "type": "text",
                "content": {
                    "url": result.url,
                    "title": result.title,
                    "text": result.text,
                    "word_count": result.stats.word_count,
                    "char_count": result.stats.char_count,
                    "line_count": result.stats.line_count,
                    "paragraph_count": result.stats.paragraph_count,
                    "sentence_count": result.stats.sentence_count,
                    "avg_words_per_sentence": result.stats.avg_words_per_sentence,
                    "extraction_strategy": extraction_info.get("strategy"),
                    "saved_files": saved_files,
                    "timestamp": result.timestamp
                },
                "error": None
            }
            
        except Exception as e:
            logger.exception("ImprovedDataScraperService: Text scraping failed")
            return {
                "success": False,
                "type": "text",
                "content": None,
                "error": f"Text scraping failed: {str(e)}"
            }
    
    def _scrape_images(self, url: str, soup: BeautifulSoup) -> dict:
        """Scrape images."""
        try:
            # Extract images
            images = ImageExtractor.extract(soup, url)
            downloaded = self._downloader.download_all(images)
            
            # Create result
            total_bytes = sum(img.size_bytes for img in downloaded)
            result = ImageResult(
                total_found=len(images),
                downloaded=len(downloaded),
                total_size_mb=total_bytes / (1024 * 1024),
                downloaded_images=[img.to_dict() for img in downloaded],
            )
            
            # Save manifest
            result.saved_files = self._storage.save_image_manifest(url, result)
            
            logger.info("ImprovedDataScraperService: Image extraction complete - found: %d, downloaded: %d", 
                       result.total_found, result.downloaded)
            
            return {
                "success": True,
                "type": "images",
                "content": {
                    "total_found": result.total_found,
                    "downloaded": result.downloaded,
                    "total_size_mb": round(result.total_size_mb, 3),
                    "images": result.downloaded_images,
                    "saved_files": result.saved_files,
                    "timestamp": result.timestamp
                },
                "error": None
            }
            
        except Exception as e:
            logger.exception("ImprovedDataScraperService: Image scraping failed")
            return {
                "success": False,
                "type": "images",
                "content": None,
                "error": f"Image scraping failed: {str(e)}"
            }
    
    def _scrape_both(self, url: str, soup: BeautifulSoup) -> dict:
        """Scrape both text and images."""
        text_result = self._scrape_text(url, soup)
        
        # Create a copy for image extraction
        soup_copy = BeautifulSoup(str(soup), "html.parser")
        image_result = self._scrape_images(url, soup_copy)
        
        # Combine results
        success = text_result["success"] or image_result["success"]
        
        combined_content = {
            "text_data": text_result["content"] if text_result["success"] else None,
            "image_data": image_result["content"] if image_result["success"] else None,
            "timestamp": datetime.now().isoformat()
        }
        
        errors = []
        if text_result["error"]:
            errors.append(f"Text: {text_result['error']}")
        if image_result["error"]:
            errors.append(f"Images: {image_result['error']}")
        
        return {
            "success": success,
            "type": "both",
            "content": combined_content,
            "error": "; ".join(errors) if errors else None
        }
    
    def _calculate_stats(self, text: str) -> TextStats:
        """Calculate text statistics."""
        if not text:
            return TextStats()
        
        words = text.split()
        
        sentences = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()
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
    
    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """Validate URL format."""
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc)
        except Exception:
            return False
