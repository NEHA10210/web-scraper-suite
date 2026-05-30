"""
Improved Page Fetcher with dynamic scraping support and fallback
"""

import logging
import requests
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Browser headers for requests
BROWSER_HEADERS = {
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

class ImprovedPageFetcher:
    """Enhanced page fetcher with dynamic scraping support."""
    
    def __init__(self, timeout: int = 15, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)
        self._dynamic_fetcher = None
        
    def fetch_page(self, url: str, use_dynamic: bool = False) -> bytes:
        """
        Fetch page with optional dynamic scraping.
        
        Args:
            url: URL to fetch
            use_dynamic: If True, try Playwright first, fallback to requests
            
        Returns:
            Page content as bytes
        """
        if use_dynamic:
            return self._fetch_with_dynamic_fallback(url)
        else:
            return self._fetch_with_requests(url)
    
    def _fetch_with_dynamic_fallback(self, url: str) -> bytes:
        """Try dynamic fetching first, fallback to requests."""
        try:
            # Try dynamic fetch first
            dynamic_fetcher = self._get_dynamic_fetcher()
            content = dynamic_fetcher.fetch_page(url)
            logger.info("ImprovedPageFetcher: Dynamic fetch successful for %s", url)
            return content
        except Exception as e:
            logger.warning("ImprovedPageFetcher: Dynamic fetch failed for %s: %s. Falling back to requests.", url, e)
            # Fallback to requests
            return self._fetch_with_requests(url)
    
    def _fetch_with_requests(self, url: str) -> bytes:
        """Fetch using requests with retry logic."""
        for attempt in range(self.max_retries):
            try:
                response = self._session.get(url, timeout=self.timeout)
                response.raise_for_status()
                logger.debug("ImprovedPageFetcher: Fetched %s (status: %d, size: %d bytes)", 
                           url, response.status_code, len(response.content))
                return response.content
            except requests.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise ValueError(f"Failed to fetch {url} after {self.max_retries} attempts: {exc}") from exc
                wait = 2 ** attempt  # Exponential backoff
                logger.warning("ImprovedPageFetcher: Attempt %d failed for %s: %s. Retrying in %.1fs...", 
                             attempt + 1, url, exc, wait)
                import time
                time.sleep(wait)
    
    def fetch_binary(self, url: str, use_dynamic: bool = False) -> bytes:
        """Fetch binary data with optional dynamic support."""
        if use_dynamic:
            try:
                dynamic_fetcher = self._get_dynamic_fetcher()
                return dynamic_fetcher.fetch_binary(url)
            except Exception as e:
                logger.warning("ImprovedPageFetcher: Dynamic binary fetch failed for %s: %s. Using requests.", url, e)
        
        # Fallback to requests for binary
        try:
            response = self._session.get(url, timeout=10, stream=True)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise ValueError(f"Failed to fetch binary from {url}: {exc}") from exc
    
    def _get_dynamic_fetcher(self):
        """Get or create dynamic fetcher instance."""
        if self._dynamic_fetcher is None:
            from .dynamic_fetcher import DynamicFetcher
            self._dynamic_fetcher = DynamicFetcher()
        return self._dynamic_fetcher
    
    def close(self):
        """Close resources."""
        if self._dynamic_fetcher:
            self._dynamic_fetcher.close()
            self._dynamic_fetcher = None
        if self._session:
            self._session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
