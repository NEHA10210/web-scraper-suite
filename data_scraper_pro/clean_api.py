"""
Clean Content API - Professional Implementation
Complete rewrite to fix all issues
"""

from .professional_extractor import ProfessionalExtractor
from .scraper_engine import AdvancedScraper
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CleanContentAPI:
    """
    Professional clean content scraper API
    """
    
    def __init__(self):
        self.extractor = ProfessionalExtractor()
        self.scraper = AdvancedScraper()
    
    async def scrape_clean_content(self, url: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Scrape and extract clean content
        
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
            extracted_content = self.extractor.extract_content(html_content, url)
            
            # Check for extraction errors
            if 'error' in extracted_content:
                return {
                    'success': False,
                    'error': extracted_content['error'],
                    'url': url
                }
            
            # Step 3: Validate and return structured result
            if not self._validate_final_result(extracted_content):
                return {
                    'success': False,
                    'error': "Extracted content does not meet quality standards",
                    'url': url
                }
            
            # Success - return structured content
            result = {
                'success': True,
                'url': url,
                'title': extracted_content['title'],
                'headings': extracted_content['headings'],
                'paragraphs': extracted_content['paragraphs']
            }
            
            logger.info(f"Successfully extracted clean content: {len(extracted_content['paragraphs'])} paragraphs")
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
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Scrape the page
            result = await self.scraper.scrape(scrape_config)
            
            return result
            
        except Exception as e:
            logger.error(f"Webpage scraping failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _validate_final_result(self, result: Dict) -> bool:
        """Validate final result meets all requirements"""
        if not result:
            return False
        
        # Check structure
        required_fields = ['title', 'headings', 'paragraphs']
        if not all(field in result for field in required_fields):
            return False
        
        # Check content quality
        paragraphs = result.get('paragraphs', [])
        if len(paragraphs) < 1:
            return False
        
        # Check for banned content
        banned_patterns = [
            'skip to main content',
            'sign up',
            'try now',
            'learn more',
            'start designing'
        ]
        
        all_text = ' '.join(paragraphs).lower()
        has_banned = any(pattern in all_text for pattern in banned_patterns)
        
        if has_banned:
            return False
        
        # Check if it's a single paragraph (should not happen for real pages)
        if len(paragraphs) == 1:
            # Allow single paragraph only if it's substantial
            if len(paragraphs[0]) < 100:
                return False
        
        return True
