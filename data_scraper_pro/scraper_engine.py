"""
Professional Data Scraper Engine
Advanced scraping with Playwright, anti-bot protection, and structured data extraction
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from bs4 import BeautifulSoup
import redis
import pymongo
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import requests
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

Base = declarative_base()

class ScrapingStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ExportFormat(Enum):
    JSON = "json"
    CSV = "csv"
    XML = "xml"

@dataclass
class ScrapingConfig:
    url: str
    selectors: Optional[Dict[str, str]] = None
    wait_for: Optional[str] = None
    scroll: bool = False
    screenshots: bool = False
    javascript: bool = True
    timeout: int = 30000
    retry_count: int = 3
    delay: float = 1.0
    user_agent: Optional[str] = None
    proxy: Optional[str] = None
    export_format: ExportFormat = ExportFormat.JSON
    save_to_db: bool = False

class ScrapingJob(Base):
    __tablename__ = 'scraping_jobs'
    
    id = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    status = Column(String, default=ScrapingStatus.PENDING.value)
    config = Column(Text)
    result = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    retry_count = Column(Integer, default=0)
    user_id = Column(String)

class AdvancedScraper:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        self.mongo_client = pymongo.MongoClient('mongodb://localhost:27017/')
        self.db_name = 'scraper_db'
        
        # Database setup
        self.engine = create_engine('sqlite:///scraper_jobs.db')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
        # User-Agent rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0'
        ]
        
        # Rate limiting
        self.last_request_time = {}
        self.min_request_interval = 1.0  # seconds
        
    def validate_url(self, url: str) -> bool:
        """Validate URL and prevent SSRF attacks"""
        try:
            parsed = urlparse(url)
            
            # Check if URL is valid
            if not all([parsed.scheme, parsed.netloc]):
                return False
            
            # Prevent SSRF - block private IPs
            hostname = parsed.hostname
            if hostname:
                # Block localhost and private IP ranges
                blocked_hosts = [
                    'localhost', '127.0.0.1', '0.0.0.0',
                    '10.', '192.168.', '172.16.', '172.17.', '172.18.', 
                    '172.19.', '172.20.', '172.21.', '172.22.', '172.23.',
                    '172.24.', '172.25.', '172.26.', '172.27.', '172.28.',
                    '172.29.', '172.30.', '172.31.'
                ]
                
                for blocked in blocked_hosts:
                    if hostname.startswith(blocked):
                        return False
            
            return True
        except Exception:
            return False
    
    def get_random_user_agent(self) -> str:
        """Get random user agent for rotation"""
        return random.choice(self.user_agents)
    
    async def rate_limit(self, domain: str):
        """Implement rate limiting per domain"""
        now = time.time()
        last_time = self.last_request_time.get(domain, 0)
        
        time_since_last = now - last_time
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        
        self.last_request_time[domain] = time.time()
    
    async def create_browser_context(self, config: ScrapingConfig) -> tuple[Browser, BrowserContext]:
        """Create browser context with anti-bot protection"""
        playwright = await async_playwright().start()
        
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--disable-plugins',
                '--disable-images' if not config.screenshots else None
            ]
        )
        
        context_options = {
            'viewport': {'width': 1920, 'height': 1080},
            'user_agent': config.user_agent or self.get_random_user_agent(),
            'ignore_https_errors': True,
            'java_script_enabled': config.javascript
        }
        
        if config.proxy:
            context_options['proxy'] = {
                'server': config.proxy,
                'bypass': 'localhost'
            }
        
        context = await browser.new_context(**context_options)
        
        # Add stealth scripts
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """)
        
        return browser, context
    
    async def handle_infinite_scroll(self, page: Page, max_scrolls: int = 10):
        """Handle infinite scroll pages"""
        last_height = await page.evaluate('document.body.scrollHeight')
        scroll_count = 0
        
        while scroll_count < max_scrolls:
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight);')
            await asyncio.sleep(2)  # Wait for content to load
            
            new_height = await page.evaluate('document.body.scrollHeight')
            if new_height == last_height:
                break
            
            last_height = new_height
            scroll_count += 1
    
    async def wait_for_content(self, page: Page, wait_for: Optional[str]):
        """Wait for specific content to load"""
        if wait_for:
            if wait_for.startswith('#'):
                await page.wait_for_selector(wait_for, timeout=10000)
            elif wait_for.startswith('//'):
                await page.wait_for_xpath(wait_for, timeout=10000)
            else:
                await page.wait_for_load_state('networkidle', timeout=10000)
        else:
            await page.wait_for_load_state('networkidle', timeout=10000)
    
    def extract_structured_data(self, html: str, config: ScrapingConfig) -> Dict[str, Any]:
        """Extract structured data from HTML"""
        soup = BeautifulSoup(html, 'lxml')
        
        # Default extraction
        data = {
            'url': config.url,
            'title': self._extract_title(soup),
            'meta': self._extract_meta(soup),
            'headings': self._extract_headings(soup),
            'paragraphs': self._extract_paragraphs(soup),
            'links': self._extract_links(soup, config.url),
            'images': self._extract_images(soup, config.url),
            'lists': self._extract_lists(soup),
            'tables': self._extract_tables(soup),
            'forms': self._extract_forms(soup),
            'structured_data': self._extract_json_ld(soup),
            'scraped_at': datetime.utcnow().isoformat()
        }
        
        # Custom selector extraction
        if config.selectors:
            custom_data = {}
            for name, selector in config.selectors.items():
                try:
                    elements = soup.select(selector)
                    custom_data[name] = [self._extract_text(elem, strip=True) for elem in elements]
                except Exception as e:
                    logger.warning(f"Failed to extract {name}: {e}")
                    custom_data[name] = []
            
            data['custom'] = custom_data
        
        return data
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract page title"""
        title_tag = soup.find('title')
        return self._extract_text(title_tag, strip=True) if title_tag else ''
    
    def _extract_meta(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract meta tags"""
        meta = {}
        for tag in soup.find_all('meta'):
            name = tag.get('name') or tag.get('property')
            content = tag.get('content')
            if name and content:
                meta[name] = content
        return meta
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all headings"""
        headings = []
        for level in range(1, 7):
            for heading in soup.find_all(f'h{level}'):
                headings.append({
                    'level': level,
                    'text': self._extract_text(heading, strip=True),
                    'id': heading.get('id', ''),
                    'class': heading.get('class', [])
                })
        return headings
    
    def _extract_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        """Extract paragraphs"""
        paragraphs = []
        for p in soup.find_all('p'):
            text = self._extract_text(p, strip=True)
            if len(text) > 20:  # Filter out very short paragraphs
                paragraphs.append(text)
        return paragraphs
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract links"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = self._extract_text(a, strip=True)
            
            # Convert to absolute URL
            absolute_url = urljoin(base_url, href)
            
            links.append({
                'url': absolute_url,
                'text': text,
                'title': a.get('title', ''),
                'target': a.get('target', ''),
                'rel': a.get('rel', [])
            })
        return links
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract images"""
        images = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src:
                absolute_url = urljoin(base_url, src)
                images.append({
                    'src': absolute_url,
                    'alt': img.get('alt', ''),
                    'title': img.get('title', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', ''),
                    'class': img.get('class', [])
                })
        return images
    
    def _extract_lists(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract lists"""
        lists = []
        for ul in soup.find_all(['ul', 'ol']):
            items = [self._extract_text(li, strip=True) for li in ul.find_all('li')]
            if items:
                lists.append({
                    'type': ul.name,
                    'class': ul.get('class', []),
                    'items': items
                })
        return lists
    
    def _extract_tables(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract tables"""
        tables = []
        for table in soup.find_all('table'):
            rows = []
            for tr in table.find_all('tr'):
                cells = [self._extract_text(td, strip=True) for td in tr.find_all(['td', 'th'])]
                if cells:
                    rows.append(cells)
            
            if rows:
                tables.append({
                    'class': table.get('class', []),
                    'rows': rows
                })
        return tables

    def _extract_text(self, element, strip: bool = False) -> str:
        """Extract text from a BeautifulSoup element without using get_text()."""
        if not element:
            return ''

        parts: List[str] = []

        # Prefer iterating over stripped_strings when available (bs4 API, not get_text)
        try:
            for s in element.stripped_strings:
                if s:
                    parts.append(str(s))
        except Exception:
            # Fallback for non-bs4 objects
            if hasattr(element, 'string') and element.string:
                parts.append(str(element.string))

        text = ' '.join(parts)
        return text.strip() if strip else text
    
    def _extract_forms(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract forms"""
        forms = []
        for form in soup.find_all('form'):
            fields = []
            for input_tag in form.find_all(['input', 'select', 'textarea']):
                fields.append({
                    'type': input_tag.get('type', 'text'),
                    'name': input_tag.get('name', ''),
                    'id': input_tag.get('id', ''),
                    'placeholder': input_tag.get('placeholder', ''),
                    'required': input_tag.has_attr('required')
                })
            
            forms.append({
                'action': form.get('action', ''),
                'method': form.get('method', 'GET'),
                'class': form.get('class', []),
                'fields': fields
            })
        return forms
    
    def _extract_json_ld(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract JSON-LD structured data"""
        structured_data = []
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                structured_data.append(data)
            except json.JSONDecodeError:
                continue
        return structured_data
    
    async def scrape(self, config: ScrapingConfig) -> Dict[str, Any]:
        """Main scraping method"""
        if not self.validate_url(config.url):
            raise ValueError("Invalid URL or blocked for security reasons")
        
        # Rate limiting
        domain = urlparse(config.url).netloc
        await self.rate_limit(domain)
        
        browser = None
        context = None
        
        try:
            # Create browser context
            browser, context = await self.create_browser_context(config)
            page = await context.new_page()
            
            # Set timeout
            page.set_default_timeout(config.timeout)
            
            # Navigate to URL
            await page.goto(config.url, wait_until='domcontentloaded')
            
            # Wait for specific content if configured
            await self.wait_for_content(page, config.wait_for)
            
            # Handle infinite scroll if enabled
            if config.scroll:
                await self.handle_infinite_scroll(page)
            
            # Add delay before extraction
            if config.delay > 0:
                await asyncio.sleep(config.delay)
            
            # Get page HTML
            html = await page.content()
            
            # Take screenshot if enabled
            screenshot = None
            if config.screenshots:
                screenshot = await page.screenshot(type='png')
            
            # Extract structured data
            data = self.extract_structured_data(html, config)
            
            # Add screenshot if taken
            if screenshot:
                import base64
                data['screenshot'] = f"data:image/png;base64,{base64.b64encode(screenshot).decode()}"
            
            # Save to database if enabled
            if config.save_to_db:
                await self.save_to_database(data)
            
            return data
            
        except Exception as e:
            logger.error(f"Scraping failed for {config.url}: {str(e)}")
            raise
        finally:
            if context:
                await context.close()
            if browser:
                await browser.close()
    
    async def save_to_database(self, data: Dict[str, Any]):
        """Save scraped data to MongoDB"""
        try:
            db = self.mongo_client[self.db_name]
            collection = db.scraped_data
            await collection.insert_one(data)
        except Exception as e:
            logger.error(f"Failed to save to database: {str(e)}")
    
    def export_data(self, data: Dict[str, Any], format: ExportFormat) -> str:
        """Export data in different formats"""
        if format == ExportFormat.JSON:
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif format == ExportFormat.CSV:
            # Convert to CSV (simplified for main content)
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write basic info
            writer.writerow(['Field', 'Value'])
            writer.writerow(['URL', data.get('url', '')])
            writer.writerow(['Title', data.get('title', '')])
            writer.writerow(['Scraped At', data.get('scraped_at', '')])
            
            # Write paragraphs
            writer.writerow([])
            writer.writerow(['Paragraphs'])
            for i, para in enumerate(data.get('paragraphs', []), 1):
                writer.writerow([f'Paragraph {i}', para])
            
            return output.getvalue()
        
        return str(data)
