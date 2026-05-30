"""
Clean Content Scraper API
Professional content extraction with proper Readability algorithm
"""

from .content_extractor import ContentExtractor, ExtractedContent
from .scraper_engine import AdvancedScraper
import asyncio
import logging
from typing import Dict, Any, Optional
import json

logger = logging.getLogger(__name__)

class CleanScraperAPI:
    """
    Clean content scraper API using professional extraction techniques
    """
    
    def __init__(self):
        self.content_extractor = ContentExtractor()
        self.scraper_engine = AdvancedScraper()
    
    async def scrape_clean_content(self, url: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Scrape and extract clean content from URL
        
        Args:
            url: URL to scrape
            config: Optional configuration
            
        Returns:
            Structured JSON with clean content
        """
        try:
            # Default configuration
            if config is None:
                config = {
                    'javascript': True,
                    'scroll': True,
                    'timeout': 30000
                }
            
            logger.info(f"Starting clean content extraction for: {url}")
            
            # Step 1: Scrape the webpage
            scrape_result = await self._scrape_webpage(url, config)
            
            if not scrape_result.get('success'):
                return {
                    'success': False,
                    'error': f"Failed to scrape webpage: {scrape_result.get('error', 'Unknown error')}",
                    'url': url
                }
            
            # Step 2: Extract clean content
            html_content = scrape_result['content']['html']
            extracted_content = self.content_extractor.extract_content(html_content, url)
            
            if not extracted_content.success:
                return {
                    'success': False,
                    'error': extracted_content.error or "Failed to extract clean content",
                    'url': url
                }
            
            # Step 3: Return structured result
            result = {
                'success': True,
                'url': url,
                'title': extracted_content.title,
                'headings': extracted_content.headings,
                'paragraphs': extracted_content.paragraphs,
                'statistics': {
                    'headings_count': len(extracted_content.headings),
                    'paragraphs_count': len(extracted_content.paragraphs),
                    'total_words': self._count_words(extracted_content.paragraphs),
                    'estimated_reading_time': self._estimate_reading_time(extracted_content.paragraphs)
                }
            }
            
            logger.info(f"Successfully extracted clean content: {len(extracted_content.paragraphs)} paragraphs")
            return result
            
        except Exception as e:
            logger.error(f"Clean scraping failed: {str(e)}")
            return {
                'success': False,
                'error': f"Scraping error: {str(e)}",
                'url': url
            }
    
    async def _scrape_webpage(self, url: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape webpage content"""
        try:
            # Configure scraper
            scrape_config = {
                'url': url,
                'javascript': config.get('javascript', True),
                'scroll': config.get('scroll', True),
                'timeout': config.get('timeout', 30000),
                'wait_for': config.get('wait_for', None),
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Scrape the page
            result = await self.scraper_engine.scrape(scrape_config)
            
            return result
            
        except Exception as e:
            logger.error(f"Webpage scraping failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _count_words(self, paragraphs: list) -> int:
        """Count total words in paragraphs"""
        total_words = 0
        for paragraph in paragraphs:
            words = paragraph.split()
            total_words += len(words)
        return total_words
    
    def _estimate_reading_time(self, paragraphs: list) -> int:
        """Estimate reading time in minutes (200 words per minute)"""
        total_words = self._count_words(paragraphs)
        reading_time = max(1, round(total_words / 200))
        return reading_time
