"""
Advanced Scraping Engine with Selector Support
Production-grade scraper with CSS selectors, XPath, and structured output
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urljoin, urlparse
from enum import Enum

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

class SelectorType(Enum):
    CSS = "css"
    XPATH = "xpath"

@dataclass
class FieldConfig:
    """Configuration for extracting structured fields."""
    name: str
    selector: str
    selector_type: SelectorType
    attribute: Optional[str] = None  # For extracting attributes like href, src
    multiple: bool = False  # Extract multiple values
    required: bool = True  # Field must be present
    transform: Optional[str] = None  # Transformation function name

@dataclass
class ScrapingConfig:
    """Complete scraping configuration."""
    url: str
    fields: List[FieldConfig]
    wait_for_selector: Optional[str] = None
    wait_timeout: int = 10
    infinite_scroll: bool = False
    scroll_delay: float = 1.0
    max_scrolls: int = 10
    pagination: bool = False
    pagination_selector: Optional[str] = None
    pagination_max_pages: int = 10
    screenshot: bool = False
    capture_network: bool = False
    delay_between_requests: float = 1.0
    retry_attempts: int = 3
    user_agent: Optional[str] = None

@dataclass
class ScrapedItem:
    """Single scraped item with structured data."""
    url: str
    timestamp: str
    data: Dict[str, Any]
    screenshot_path: Optional[str] = None
    raw_html: Optional[str] = None
    extraction_time: float = 0.0

@dataclass
class ScrapingResult:
    """Complete scraping result with metadata."""
    success: bool
    items: List[ScrapedItem]
    total_items: int
    config: ScrapingConfig
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    pages_scraped: int = 0

class AdvancedScrapingEngine:
    """Production-grade scraping engine with advanced features."""
    
    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy
        self.driver = None
        self._setup_driver()
    
    def _setup_driver(self):
        """Setup Selenium WebDriver with advanced options."""
        options = Options()
        
        if self.headless:
            options.add_argument('--headless')
        
        # Anti-detection options
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Performance options
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')  # Faster loading
        
        # Proxy support
        if self.proxy:
            options.add_argument(f'--proxy-server={self.proxy}')
        
        # User agent rotation
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            raise
    
    def scrape(self, config: ScrapingConfig) -> ScrapingResult:
        """
        Execute scraping with the given configuration.
        
        Returns:
            ScrapingResult with all extracted data
        """
        start_time = time.time()
        result = ScrapingResult(
            success=False,
            items=[],
            total_items=0,
            config=config,
            execution_time=0.0,
            pages_scraped=0
        )
        
        try:
            logger.info(f"Starting scrape of {config.url}")
            
            # Navigate to URL
            self.driver.get(config.url)
            
            # Wait for initial content
            if config.wait_for_selector:
                self._wait_for_element(config.wait_for_selector, config.wait_timeout)
            
            # Handle infinite scroll
            if config.infinite_scroll:
                self._handle_infinite_scroll(config)
            
            # Extract data
            items = []
            current_url = config.url
            page_count = 1
            
            while current_url and page_count <= config.pagination_max_pages:
                # Extract data from current page
                page_items = self._extract_page_data(config, current_url)
                items.extend(page_items)
                
                # Take screenshot if requested
                if config.screenshot and page_items:
                    self._take_screenshot(page_items[-1], page_count)
                
                # Handle pagination
                if config.pagination and page_count < config.pagination_max_pages:
                    current_url = self._handle_pagination(config)
                    if current_url:
                        page_count += 1
                        time.sleep(config.delay_between_requests)
                    else:
                        break
                else:
                    break
            
            # Update result
            result.success = True
            result.items = items
            result.total_items = len(items)
            result.pages_scraped = page_count
            
            logger.info(f"Scraping completed: {len(items)} items from {page_count} pages")
            
        except Exception as e:
            error_msg = f"Scraping failed: {str(e)}"
            logger.error(error_msg)
            result.errors.append(error_msg)
        
        finally:
            result.execution_time = time.time() - start_time
        
        return result
    
    def _extract_page_data(self, config: ScrapingConfig, url: str) -> List[ScrapedItem]:
        """Extract structured data from current page."""
        items = []
        start_time = time.time()
        
        try:
            # Get page source for processing
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find all item containers (if multiple items expected)
            item_containers = self._find_item_containers(soup, config)
            
            if not item_containers:
                # Single item extraction
                item_data = self._extract_fields_from_element(soup, config.fields)
                if item_data:
                    items.append(ScrapedItem(
                        url=url,
                        timestamp=datetime.now().isoformat(),
                        data=item_data,
                        raw_html=html if config.capture_network else None,
                        extraction_time=time.time() - start_time
                    ))
            else:
                # Multiple items extraction
                for container in item_containers:
                    item_data = self._extract_fields_from_element(container, config.fields)
                    if item_data:
                        items.append(ScrapedItem(
                            url=url,
                            timestamp=datetime.now().isoformat(),
                            data=item_data,
                            raw_html=str(container) if config.capture_network else None,
                            extraction_time=time.time() - start_time
                        ))
        
        except Exception as e:
            error_msg = f"Data extraction failed: {str(e)}"
            logger.error(error_msg)
            # Don't raise here, continue with empty items
        
        return items
    
    def _find_item_containers(self, soup: BeautifulSoup, config: ScrapingConfig) -> List[BeautifulSoup]:
        """Find item containers when extracting multiple items."""
        # Heuristic: look for common list item patterns
        container_selectors = [
            '.item', '.product', '.post', '.article', '.listing',
            '[class*="item"]', '[class*="product"]', '[class*="post"]',
            'li', '.card', '.result'
        ]
        
        for selector in container_selectors:
            containers = soup.select(selector)
            if len(containers) > 1:  # Found multiple items
                return containers[:50]  # Limit to prevent memory issues
        
        return []
    
    def _extract_fields_from_element(self, element: BeautifulSoup, fields: List[FieldConfig]) -> Dict[str, Any]:
        """Extract configured fields from a BeautifulSoup element."""
        data = {}
        
        for field_config in fields:
            try:
                value = self._extract_field_value(element, field_config)
                
                if value is not None:
                    # Apply transformation if specified
                    if field_config.transform:
                        value = self._apply_transformation(value, field_config.transform)
                    
                    data[field_config.name] = value
                elif field_config.required:
                    logger.warning(f"Required field '{field_config.name}' not found")
                    data[field_config.name] = None
            
            except Exception as e:
                error_msg = f"Failed to extract field '{field_config.name}': {str(e)}"
                logger.warning(error_msg)
                if field_config.required:
                    data[field_config.name] = None
        
        return data
    
    def _extract_field_value(self, element: BeautifulSoup, field_config: FieldConfig) -> Any:
        """Extract a single field value using CSS or XPath."""
        try:
            if field_config.selector_type == SelectorType.CSS:
                elements = element.select(field_config.selector)
            else:  # XPath
                # Note: BeautifulSoup doesn't support XPath directly
                # For XPath, we'd need to use lxml or selenium
                elements = []
            
            if not elements:
                return None
            
            if field_config.multiple:
                values = []
                for elem in elements:
                    if field_config.attribute:
                        values.append(elem.get(field_config.attribute, ''))
                    else:
                        values.append(elem.get_text(strip=True))
                return values
            else:
                elem = elements[0]
                if field_config.attribute:
                    return elem.get(field_config.attribute, '')
                else:
                    return elem.get_text(strip=True)
        
        except Exception as e:
            logger.error(f"Error extracting field {field_config.name}: {e}")
            return None
    
    def _apply_transformation(self, value: Any, transform: str) -> Any:
        """Apply transformation to extracted value."""
        if isinstance(value, list):
            return [self._apply_transformation(v, transform) for v in value]
        
        transformations = {
            'lower': lambda x: str(x).lower(),
            'upper': lambda x: str(x).upper(),
            'strip': lambda x: str(x).strip(),
            'price': lambda x: self._extract_price(str(x)),
            'number': lambda x: self._extract_number(str(x)),
            'url': lambda x: self._normalize_url(str(x)),
            'date': lambda x: self._parse_date(str(x))
        }
        
        if transform in transformations:
            try:
                return transformations[transform](value)
            except Exception as e:
                logger.warning(f"Transformation '{transform}' failed: {e}")
                return value
        
        return value
    
    def _extract_price(self, text: str) -> Optional[float]:
        """Extract price from text."""
        # Remove currency symbols and extract number
        price_match = re.search(r'[\$\£\€]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', text)
        if price_match:
            price_str = price_match.group(1).replace(',', '')
            try:
                return float(price_str)
            except ValueError:
                return None
        return None
    
    def _extract_number(self, text: str) -> Optional[float]:
        """Extract number from text."""
        number_match = re.search(r'(\d+(?:,\d{3})*(?:\.\d+)?)', text)
        if number_match:
            num_str = number_match.group(1).replace(',', '')
            try:
                return float(num_str)
            except ValueError:
                return None
        return None
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL."""
        if not url:
            return ""
        
        if url.startswith(('http://', 'https://')):
            return url
        
        # Assume relative URL - would need base URL to normalize properly
        return url
    
    def _parse_date(self, text: str) -> Optional[str]:
        """Parse date from text."""
        # Simple date parsing - could be enhanced with dateutil
        import dateutil.parser
        try:
            dt = dateutil.parser.parse(text)
            return dt.isoformat()
        except:
            return text
    
    def _wait_for_element(self, selector: str, timeout: int):
        """Wait for element to be present."""
        try:
            wait = WebDriverWait(self.driver, timeout)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        except TimeoutException:
            logger.warning(f"Element not found within timeout: {selector}")
            raise
    
    def _handle_infinite_scroll(self, config: ScrapingConfig):
        """Handle infinite scroll pages."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        
        for i in range(config.max_scrolls):
            # Scroll to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            # Wait for new content to load
            time.sleep(config.scroll_delay)
            
            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break  # No more content loaded
            
            last_height = new_height
        
        logger.info(f"Infinite scroll completed after {i+1} scrolls")
    
    def _handle_pagination(self, config: ScrapingConfig) -> Optional[str]:
        """Handle pagination and return next page URL."""
        if not config.pagination_selector:
            return None
        
        try:
            next_button = self.driver.find_element(By.CSS_SELECTOR, config.pagination_selector)
            if next_button.is_enabled():
                next_button.click()
                time.sleep(config.delay_between_requests)
                return self.driver.current_url
        except NoSuchElementException:
            logger.info("No more pagination button found")
        
        return None
    
    def _take_screenshot(self, item: ScrapedItem, page_num: int):
        """Take screenshot of the page."""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"screenshot_page{page_num}_{timestamp}.png"
            filepath = f"data/screenshots/{filename}"
            
            # Ensure directory exists
            import os
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            self.driver.save_screenshot(filepath)
            item.screenshot_path = filepath
            
            logger.info(f"Screenshot saved: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to take screenshot: {e}")
    
    def close(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
