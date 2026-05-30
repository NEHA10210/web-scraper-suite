"""
Enhanced Data Scraper Service
Integrates intelligent page detection, crawling, and enhanced text extraction.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Import existing components
from .service import (
    PageFetcher, DynamicPageFetcher, MetadataExtractor, TextExtractor,
    ImageExtractor, ImageDownloader, StorageService,
    TextResult, TextStats, ImageResult, REQUEST_TIMEOUT,
    IMAGE_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF, IMAGE_DOWNLOAD_CAP,
    IMAGE_RATE_LIMIT, NOISE_TAGS, VALID_IMAGE_EXTENSIONS,
    BROWSER_HEADERS, DATE_META_SELECTORS
)

# Import new enhanced components
from .page_classifier import PageClassifier
from .link_crawler import LinkCrawler
from .enhanced_text_extractor import EnhancedTextExtractor


class EnhancedDataScraperService:
    """
    Enhanced Data Scraper with intelligent page detection and crawling.
    
    Features:
    - Automatic page type detection (article, homepage, listing)
    - Smart crawling for homepages/listings
    - Dynamic scraping auto-retry for low-quality content
    - Enhanced text extraction with quality scoring
    - Detailed logging and warnings
    """

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
        """
        Enhanced main entry point with intelligent page detection and crawling.
        
        Args:
            url: URL to scrape
            scrape_type: Type of scraping ("text", "images", or "both")
            use_dynamic: If True, use Playwright for dynamic content
        """
        if not self._is_valid_url(url):
            return {"error": "Invalid URL format."}

        if scrape_type not in self.VALID_SCRAPE_TYPES:
            return {
                "error": (
                    f"Invalid scrape_type '{scrape_type}'. "
                    f"Valid options: {', '.join(sorted(self.VALID_SCRAPE_TYPES))}."
                )
            }

        logs = []
        
        # Initial fetch attempt
        fetcher = self._get_fetcher(use_dynamic)
        fetcher_type = "Dynamic" if use_dynamic else "Static"
        logs.append(f"Using {fetcher_type} fetcher for {url}")
        logger.info("EnhancedDataScraperService: Using %s fetcher for %s", fetcher_type, url)
        
        try:
            html = fetcher.fetch_page(url)
        except ValueError as exc:
            logger.error("Page fetch failed for %s: %s", url, exc)
            return {"error": str(exc)}
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Classify the page
        classifier = PageClassifier()
        classification = classifier.classify_page(soup, url)
        logs.append(f"Detected page type: {classification['page_type']} (confidence: {classification['confidence']:.2f})")
        
        # Smart scraping strategy based on page type
        if classification['page_type'] == 'article':
            # Single article - extract content directly
            if scrape_type == "text":
                result = self._run_enhanced_text_pipeline(url, soup, logs)
                # Check content quality and retry with dynamic if needed
                if (not use_dynamic and 
                    result.get('content', {}).get('word_count', 0) < 100 and
                    result.get('extraction_metadata', {}).get('quality_score', 1.0) < 0.5):
                    logs.append("Low quality content detected, retrying with dynamic scraping...")
                    try:
                        dynamic_fetcher = self._get_fetcher(True)
                        html = dynamic_fetcher.fetch_page(url)
                        soup = BeautifulSoup(html, "html.parser")
                        result = self._run_enhanced_text_pipeline(url, soup, logs)
                        result['logs'] = logs + result.get('logs', [])
                        result['warnings'] = result.get('warnings', []) + ["Used dynamic scraping due to low static content quality"]
                    except Exception as e:
                        logs.append(f"Dynamic retry failed: {str(e)}")
                        result['logs'] = logs
                return result
            elif scrape_type == "images":
                return self._run_image_pipeline(url, soup, logs)
            else:  # both
                text_result = self._run_enhanced_text_pipeline(url, deepcopy(soup), logs)
                image_result = self._run_image_pipeline(url, soup, logs)
                return self._combine_results(text_result, image_result, logs)
                
        elif classification['page_type'] in ['homepage', 'listing']:
            # Homepage or listing - extract links and crawl
            logs.append(f"Extracting and crawling links from {classification['page_type']}")
            
            # Extract links
            crawler = LinkCrawler(max_links=8)  # Limit for performance
            links = crawler.extract_links(soup, url)
            logs.append(f"Found {len(links)} potential links to crawl")
            
            if not links:
                logs.append("No suitable links found, falling back to page content")
                if scrape_type == "text":
                    return self._run_enhanced_text_pipeline(url, soup, logs)
                elif scrape_type == "images":
                    return self._run_image_pipeline(url, soup, logs)
                else:
                    text_result = self._run_enhanced_text_pipeline(url, deepcopy(soup), logs)
                    image_result = self._run_image_pipeline(url, soup, logs)
                    return self._combine_results(text_result, image_result, logs)
            
            # Crawl linked pages
            crawled_results = []
            for i, link in enumerate(links[:5]):  # Limit to 5 for performance
                try:
                    logs.append(f"Crawling link {i+1}: {link.url}")
                    link_html = fetcher.fetch_page(link.url)
                    link_soup = BeautifulSoup(link_html, "html.parser")
                    
                    if scrape_type in ["text", "both"]:
                        link_result = self._run_enhanced_text_pipeline(link.url, link_soup, [])
                        link_result['source_url'] = link.url
                        link_result['source_title'] = link.title or link.text
                        crawled_results.append(link_result)
                        
                except Exception as e:
                    logs.append(f"Failed to crawl {link.url}: {str(e)}")
                    continue
            
            # Combine results
            if crawl_result := self._combine_crawled_results(crawled_results, logs):
                if scrape_type == "both":
                    # Also get images from main page
                    image_result = self._run_image_pipeline(url, soup, logs)
                    return self._combine_results(crawl_result, image_result, logs)
                return crawl_result
            else:
                logs.append("Crawling failed, falling back to main page content")
                if scrape_type == "text":
                    return self._run_enhanced_text_pipeline(url, soup, logs)
                elif scrape_type == "images":
                    return self._run_image_pipeline(url, soup, logs)
                else:
                    text_result = self._run_enhanced_text_pipeline(url, deepcopy(soup), logs)
                    image_result = self._run_image_pipeline(url, soup, logs)
                    return self._combine_results(text_result, image_result, logs)
        
        # Default fallback
        if scrape_type == "text":
            return self._run_enhanced_text_pipeline(url, soup, logs)
        elif scrape_type == "images":
            return self._run_image_pipeline(url, soup, logs)
        else:
            text_result = self._run_enhanced_text_pipeline(url, deepcopy(soup), logs)
            image_result = self._run_image_pipeline(url, soup, logs)
            return self._combine_results(text_result, image_result, logs)

    def _run_enhanced_text_pipeline(self, url: str, soup: BeautifulSoup, logs: list = None) -> dict:
        """Enhanced text extraction with quality validation."""
        if logs is None:
            logs = []
            
        try:
            # Extract metadata
            metadata = MetadataExtractor.extract(soup, url)
            
            # Use enhanced text extractor
            extractor = EnhancedTextExtractor()
            text, extraction_metadata = extractor.extract(soup, url)
            
            # Calculate stats
            stats = self._calculate_text_stats(text)
            
            # Create result
            result = TextResult(url=url, title=metadata.title, text=text, stats=stats)
            
            # Validate content quality
            quality_issues = []
            warnings = []
            
            if stats.word_count < 50:
                quality_issues.append("Very low word count")
                warnings.append("Low content extracted (less than 50 words)")
            elif stats.word_count < 100:
                quality_issues.append("Low word count")
                warnings.append("Limited content extracted (less than 100 words)")
            
            if extraction_metadata.get('quality_score', 1.0) < 0.5:
                quality_issues.append("Low content quality detected")
                warnings.append("Content quality may be poor")
            
            # Save if content is meaningful
            saved_files = []
            if text.strip() and stats.word_count >= 20:
                saved_files = self._storage.save_text(result)
            else:
                logger.warning("Insufficient text content extracted from %s.", url)
            
            logs.append(f"Extracted {stats.word_count} words with quality score {extraction_metadata.get('quality_score', 0):.2f}")
            
            return {
                "type": "text",
                "success": True,
                "content": result.to_dict(),
                "saved_files": saved_files,
                "timestamp": result.timestamp,
                "logs": logs,
                "warnings": warnings,
                "extraction_metadata": extraction_metadata,
                "quality_issues": quality_issues
            }
            
        except Exception:
            logger.exception("Enhanced text pipeline failed for %s.", url)
            return {"error": "Text scraping failed due to an internal error."}

    def _run_image_pipeline(self, url: str, soup: BeautifulSoup, logs: list = None) -> dict:
        """Enhanced image pipeline with logging."""
        if logs is None:
            logs = []
            
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
            
            logs.append(f"Found {len(images)} images, downloaded {len(downloaded)}")
            
            return {
                "type": "images",
                "success": True,
                "images": result.to_dict(),
                "saved_files": result.saved_files,
                "timestamp": result.timestamp,
                "logs": logs
            }
            
        except Exception:
            logger.exception("Image pipeline failed for %s.", url)
            return {"error": "Image scraping failed due to an internal error."}

    def _combine_results(self, text_result: dict, image_result: dict, logs: list = None) -> dict:
        """Combine text and image results."""
        if logs is None:
            logs = []
        
        combined_logs = logs
        combined_logs.extend(text_result.get('logs', []))
        combined_logs.extend(image_result.get('logs', []))
        
        warnings = text_result.get('warnings', []) + image_result.get('warnings', [])
        
        return {
            "success": True,
            "type": "both",
            "text_data": text_result,
            "image_data": image_result,
            "timestamp": datetime.now().isoformat(),
            "logs": combined_logs,
            "warnings": warnings
        }

    def _combine_crawled_results(self, crawled_results: list, logs: list = None) -> dict:
        """Combine results from multiple crawled pages."""
        if not crawled_results:
            return None
            
        if logs is None:
            logs = []
        
        # Combine all text content
        combined_text = []
        total_word_count = 0
        total_char_count = 0
        all_warnings = []
        
        for result in crawled_results:
            content = result.get('content', {})
            if content.get('text'):
                # Add source information
                source_title = result.get('source_title', 'Untitled')
                source_url = result.get('source_url', '')
                combined_text.append(f"\n=== {source_title} ===\n{content['text']}")
                
                total_word_count += content.get('word_count', 0)
                total_char_count += content.get('char_count', 0)
            
            all_warnings.extend(result.get('warnings', []))
        
        if not combined_text:
            logs.append("No meaningful content found in crawled pages")
            return None
        
        final_text = '\n'.join(combined_text)
        
        # Create combined result
        combined_stats = TextStats(
            word_count=total_word_count,
            char_count=total_char_count,
            line_count=len(final_text.split('\n')),
            paragraph_count=len([p for p in final_text.split('\n\n') if p.strip()]),
            sentence_count=len([s for s in final_text.split('. ') if s.strip()]),
            avg_words_per_sentence=total_word_count / len([s for s in final_text.split('. ') if s.strip()]) if final_text else 0
        )
        
        combined_result = TextResult(
            url="multiple_pages",
            title=f"Combined Content from {len(crawled_results)} Pages",
            text=final_text,
            stats=combined_stats
        )
        
        logs.append(f"Combined content from {len(crawled_results)} pages: {total_word_count} total words")
        
        return {
            "type": "text",
            "success": True,
            "content": combined_result.to_dict(),
            "crawled_pages": len(crawled_results),
            "sources": [
                {
                    "url": r.get('source_url', ''),
                    "title": r.get('source_title', ''),
                    "word_count": r.get('content', {}).get('word_count', 0)
                }
                for r in crawled_results
            ],
            "timestamp": datetime.now().isoformat(),
            "logs": logs,
            "warnings": all_warnings
        }

    def _calculate_text_stats(self, text: str) -> TextStats:
        """Calculate text statistics."""
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
            line_count=len(text.split('\n')),
            paragraph_count=len(paragraphs),
            sentence_count=len(sentences),
            avg_words_per_sentence=round(avg_words, 1),
        )

    def _get_fetcher(self, use_dynamic: bool = False):
        """Get appropriate fetcher based on use_dynamic flag."""
        if use_dynamic:
            # Initialize dynamic fetcher on demand
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
