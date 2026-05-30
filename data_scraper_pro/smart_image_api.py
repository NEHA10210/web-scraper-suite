"""
Smart Image Scraper API
API endpoint for smart image extraction with noise filtering.
"""

import aiohttp
import asyncio
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
import logging

from .smart_image_extractor import SmartImageExtractor

logger = logging.getLogger(__name__)


class SmartImageScraperAPI:
    """API for smart image scraping with filtering."""
    
    def __init__(self):
        self.extractor = SmartImageExtractor(min_width=100, min_height=100)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def scrape_images(self, url: str, config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Scrape images from URL with smart filtering.
        
        Args:
            url: Target URL
            config: Optional configuration
            
        Returns:
            Dictionary with extraction results
        """
        config = config or {}
        
        try:
            # Fetch page
            html = await self._fetch_page(url)
            if not html:
                return {
                    'success': False,
                    'error': 'Failed to fetch page'
                }
            
            # Parse HTML
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract images
            result = self.extractor.extract_images(soup, url)
            
            # Add metadata
            result['success'] = True
            result['url'] = url
            
            return result
            
        except Exception as e:
            logger.error(f"Error scraping images from {url}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch page HTML."""
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            )
        
        try:
            async with self.session.get(url, timeout=30) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.error(f"HTTP {response.status} for {url}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()
