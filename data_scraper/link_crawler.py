"""
Link Crawler Module
Extracts and filters meaningful links from web pages.
"""

from dataclasses import dataclass
from typing import List, Set, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import re

@dataclass
class LinkInfo:
    """Information about a discovered link."""
    url: str
    title: str
    text: str
    is_internal: bool
    is_article: bool
    priority: int  # Higher = more likely to be good content

class LinkCrawler:
    """Extracts and filters links for crawling."""
    
    def __init__(self, max_links: int = 10):
        self.max_links = max_links
        
        # Patterns to avoid
        self.exclude_patterns = [
            r'login', r'register', r'signup', r'cart', r'checkout',
            r'admin', r'account', r'profile', r'settings',
            r'javascript:', r'mailto:', r'tel:', r'#',
            r'\.pdf$', r'\.jpg$', r'\.png$', r'\.gif$',
            r'facebook\.com', r'twitter\.com', r'instagram\.com',
            r'youtube\.com', r'linkedin\.com'
        ]
        
        # Article indicators
        self.article_patterns = [
            r'article', r'post', r'story', r'news', r'blog',
            r'tutorial', r'guide', r'review', r'analysis'
        ]
    
    def extract_links(self, soup: BeautifulSoup, base_url: str) -> List[LinkInfo]:
        """
        Extract and filter meaningful links from the page.
        
        Args:
            soup: BeautifulSoup object of the page
            base_url: Base URL for resolving relative links
            
        Returns:
            List of LinkInfo objects sorted by priority
        """
        base_domain = urlparse(base_url).netloc.lower()
        raw_links = []
        
        # Find all links with href
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').strip()
            if not href:
                continue
            
            # Skip empty or invalid links
            if href.startswith('#') or len(href) < 2:
                continue
            
            # Resolve relative URL
            full_url = urljoin(base_url, href)
            
            # Parse URL
            parsed = urlparse(full_url)
            if not parsed.scheme or not parsed.netloc:
                continue
            
            # Check if should be excluded
            if self._should_exclude(full_url):
                continue
            
            # Get link text and title
            text = link.get_text(strip=True)
            title = link.get('title', '') or text
            
            # Check if internal link
            is_internal = parsed.netloc.lower() == base_domain
            
            # Check if likely article
            is_article = self._is_likely_article(full_url, text, title)
            
            # Calculate priority
            priority = self._calculate_priority(
                full_url, text, title, is_internal, is_article, link
            )
            
            raw_links.append(LinkInfo(
                url=full_url,
                title=title,
                text=text,
                is_internal=is_internal,
                is_article=is_article,
                priority=priority
            ))
        
        # Remove duplicates
        unique_links = self._remove_duplicates(raw_links)
        
        # Sort by priority and limit
        unique_links.sort(key=lambda x: x.priority, reverse=True)
        return unique_links[:self.max_links]
    
    def _should_exclude(self, url: str) -> bool:
        """Check if URL should be excluded."""
        url_lower = url.lower()
        
        for pattern in self.exclude_patterns:
            if re.search(pattern, url_lower):
                return True
        
        return False
    
    def _is_likely_article(self, url: str, text: str, title: str) -> bool:
        """Check if link is likely to point to an article."""
        combined_text = f"{url} {text} {title}".lower()
        
        for pattern in self.article_patterns:
            if re.search(pattern, combined_text):
                return True
        
        # Check for date patterns (common in articles)
        date_pattern = r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}'
        if re.search(date_pattern, combined_text):
            return True
        
        return False
    
    def _calculate_priority(self, url: str, text: str, title: str, 
                          is_internal: bool, is_article: bool, link_element) -> int:
        """Calculate priority score for a link."""
        priority = 0
        
        # Base priority for internal links
        if is_internal:
            priority += 2
        
        # Article links get higher priority
        if is_article:
            priority += 3
        
        # Links with good text get higher priority
        if len(text) > 10:
            priority += 1
        if len(text) > 30:
            priority += 1
        
        # Links in main content areas get higher priority
        parent = link_element.parent
        if parent:
            parent_tag = parent.name.lower()
            if parent_tag in ['article', 'main', 'section']:
                priority += 2
            elif parent_tag in ['nav', 'footer', 'header']:
                priority -= 2
        
        # Links with certain classes get higher priority
        classes = link_element.get('class', [])
        for class_name in classes:
            class_lower = class_name.lower()
            if any(keyword in class_lower for keyword in ['content', 'article', 'post']):
                priority += 2
            elif any(keyword in class_lower for keyword in ['nav', 'menu', 'sidebar']):
                priority -= 1
        
        # URL patterns
        url_lower = url.lower()
        if any(keyword in url_lower for keyword in ['article', 'post', 'story']):
            priority += 2
        
        # Avoid very short or generic text
        if len(text) < 3 or text.lower() in ['more', 'read more', 'click here', 'link']:
            priority -= 2
        
        return max(priority, 0)
    
    def _remove_duplicates(self, links: List[LinkInfo]) -> List[LinkInfo]:
        """Remove duplicate links based on URL."""
        seen_urls = set()
        unique_links = []
        
        for link in links:
            # Normalize URL for comparison
            normalized = urlunparse((
                urlparse(link.url).scheme,
                urlparse(link.url).netloc.lower(),
                urlparse(link.url).path,
                '', '', ''  # Remove params, query, fragment
            ))
            
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                unique_links.append(link)
        
        return unique_links
