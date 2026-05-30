"""
Professional Content Extraction Engine
Complete rewrite to fix all issues
"""

from readability import Document
from bs4 import BeautifulSoup, Comment
import re
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class ProfessionalExtractor:
    """
    Professional content extractor that works like browser Reader Mode
    """
    
    def __init__(self):
        # Noise selectors to remove completely
        self.noise_selectors = [
            # Navigation
            'nav', '[role="navigation"]', '.nav', '.navigation', '.menu', 
            '#nav', '#navigation', '#menu', '.navbar', '.header-nav',
            
            # Headers and footers
            'header', 'footer', '.header', '.footer', '#header', '#footer',
            '.site-header', '.site-footer', '.page-header', '.page-footer',
            
            # Sidebars and widgets
            'aside', 'sidebar', '.sidebar', '.aside', '#sidebar', '#aside',
            '.widget', '.widgets', '#widget', '#widgets', '.side-panel',
            
            # Ads and promotions
            'ad', 'ads', 'advertisement', '.ad', '.ads', '.advertisement',
            '#ad', '#ads', '#advertisement', '.banner', '.promo', '.promotion',
            '.commercial', '.sponsored',
            
            # Social and sharing
            'social', '.social', '#social', '.share', '.sharing', '#share',
            '.follow', '.follow-us', '.social-media', '.social-links',
            
            # Comments and interactions
            'comments', '.comments', '#comments', '.comment', '.reply',
            '.discussion', '.feedback', '.interaction',
            
            # Forms and buttons
            'form', 'button', 'input', 'select', 'textarea', '.form',
            'button', '.button', '.btn', '#btn', '.cta', '.action',
            
            # Scripts and styles
            'script', 'style', 'noscript', 'link[rel="stylesheet"]',
            
            # Common noise patterns
            '.popup', '.modal', '.overlay', '.cookie', '.cookie-notice',
            '.breadcrumb', '.breadcrumbs', '.pagination', '.pager',
            '.newsletter', '.subscribe', '.signup', '.registration',
            
            # Specific patterns
            '[class*="nav"]', '[class*="menu"]', '[class*="sidebar"]',
            '[class*="ad"]', '[class*="social"]', '[class*="comment"]',
            '[class*="footer"]', '[class*="header"]', '[class*="banner"]',
            '[id*="nav"]', '[id*="menu"]', '[id*="sidebar"]', '[id*="ad"]',
            '[id*="social"]', '[id*="comment"]', '[id*="footer"]', '[id*="header"]'
        ]
        
        # Boilerplate text patterns to remove
        self.boilerplate_patterns = [
            r'skip to main content',
            r'skip to content',
            r'sign up', r'signin', r'sign in', r'log in', r'login', r'register',
            r'try now', r'get started', r'start now', r'begin',
            r'learn more', r'read more', r'find out more', r'discover',
            r'click here', r'follow us', r'subscribe', r'newsletter',
            r'privacy policy', r'terms of service', r'terms of use',
            r'cookie policy', r'all rights reserved', r'copyright',
            r'contact us', r'about us', r'help', r'support',
            r'share this', r'like this', r'tweet this', r'facebook',
            r'twitter', r'instagram', r'linkedin', r'youtube',
            r'back to top', r'return to top', r'jump to navigation',
            r'start designing', r'design now', r'create now',
            r'free trial', r'upgrade now', r'buy now', r'shop now',
            r'we use cookies', r'by continuing', r'cookie notice'
        ]

    def extract_content(self, html: str, url: str) -> Dict:
        """
        Extract clean content using professional methods
        
        Args:
            html: Raw HTML content
            url: Source URL
            
        Returns:
            Dict with structured content
        """
        try:
            # Method 1: Readability algorithm (preferred)
            result = self._extract_with_readability(html, url)
            if result and self._validate_result(result):
                logger.info("Successfully extracted with Readability")
                return result
            
            # Method 2: Semantic HTML extraction
            result = self._extract_semantic(html, url)
            if result and self._validate_result(result):
                logger.info("Successfully extracted with semantic HTML")
                return result
            
            # Method 3: Heuristic extraction with largest content block
            result = self._extract_heuristic(html, url)
            if result and self._validate_result(result):
                logger.info("Successfully extracted with heuristics")
                return result
            
            # If all methods fail
            return {
                "title": "",
                "headings": [],
                "paragraphs": [],
                "error": "Could not extract readable content"
            }
            
        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}")
            return {
                "title": "",
                "headings": [],
                "paragraphs": [],
                "error": f"Extraction error: {str(e)}"
            }

    def _extract_with_readability(self, html: str, url: str) -> Optional[Dict]:
        """Extract using Mozilla Readability algorithm"""
        try:
            # Create Readability document
            doc = Document(html, url=url)
            
            # Get the cleaned HTML
            clean_html = doc.summary()
            
            # Parse cleaned HTML
            soup = BeautifulSoup(clean_html, 'html.parser')

            # IMPORTANT: Readability can still include some UI/noise. Strip again.
            self._remove_all_noise(soup)
            
            # Extract structured content
            title = doc.title() or self._extract_title_from_soup(soup)
            headings = self._extract_headings_from_soup(soup)
            paragraphs = self._extract_paragraphs_from_soup(soup)

            # If we still got a single merged paragraph, split into multiple paragraphs.
            paragraphs = self._ensure_paragraph_structure(paragraphs)
            
            return {
                "title": self._clean_text(title),
                "headings": [self._clean_text(h) for h in headings if h.strip()],
                "paragraphs": [self._clean_text(p) for p in paragraphs if p.strip()]
            }
            
        except Exception as e:
            logger.warning(f"Readability extraction failed: {str(e)}")
            return None

    def _extract_semantic(self, html: str, url: str) -> Optional[Dict]:
        """Extract using semantic HTML5 tags"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove noise first
            self._remove_all_noise(soup)
            
            # Find main content using semantic tags
            main_content = None
            semantic_selectors = [
                'main', 'article', '[role="main"]', '.main-content',
                '.article-content', '.post-content', '.entry-content'
            ]
            
            for selector in semantic_selectors:
                element = soup.select_one(selector)
                if element and self._has_meaningful_content(element):
                    main_content = element
                    break
            
            if not main_content:
                return None
            
            # Extract content
            title = self._extract_title_from_soup(soup)
            headings = self._extract_headings_from_soup(main_content)
            paragraphs = self._extract_paragraphs_from_soup(main_content)

            paragraphs = self._ensure_paragraph_structure(paragraphs)
            
            return {
                "title": self._clean_text(title),
                "headings": [self._clean_text(h) for h in headings if h.strip()],
                "paragraphs": [self._clean_text(p) for p in paragraphs if p.strip()]
            }
            
        except Exception as e:
            logger.warning(f"Semantic extraction failed: {str(e)}")
            return None

    def _extract_heuristic(self, html: str, url: str) -> Optional[Dict]:
        """Extract using heuristic approach - largest content block"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove noise first
            self._remove_all_noise(soup)
            
            # Find the element with the most meaningful content
            candidates = []
            
            # Check common content containers
            for element in soup.find_all(['div', 'section', 'article', 'main']):
                if self._has_meaningful_content(element):
                    # Score based on paragraph count and text length
                    paragraphs = element.find_all('p')
                    text_length = len(self._get_clean_text_from_element(element))
                    score = len(paragraphs) * 10 + text_length
                    candidates.append((element, score))
            
            if not candidates:
                return None
            
            # Select the best candidate
            best_element = max(candidates, key=lambda x: x[1])[0]
            
            # Extract content
            title = self._extract_title_from_soup(soup)
            headings = self._extract_headings_from_soup(best_element)
            paragraphs = self._extract_paragraphs_from_soup(best_element)

            paragraphs = self._ensure_paragraph_structure(paragraphs)
            
            return {
                "title": self._clean_text(title),
                "headings": [self._clean_text(h) for h in headings if h.strip()],
                "paragraphs": [self._clean_text(p) for p in paragraphs if p.strip()]
            }
            
        except Exception as e:
            logger.warning(f"Heuristic extraction failed: {str(e)}")
            return None

    def _remove_all_noise(self, soup: BeautifulSoup):
        """Remove all noise elements from the DOM"""
        # Remove elements by selectors
        for selector in self.noise_selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except:
                continue
        
        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove elements with noise attributes
        for element in soup.find_all():
            if element and hasattr(element, 'attrs'):
                # Check class attributes
                class_attr = element.attrs.get('class', [])
                if class_attr:
                    class_str = ' '.join(class_attr).lower()
                    if any(noise in class_str for noise in ['nav', 'menu', 'footer', 'header', 'sidebar', 'ad', 'social', 'comment', 'banner']):
                        element.decompose()
                        continue
                
                # Check ID attributes
                id_attr = element.attrs.get('id', '')
                if id_attr and any(noise in id_attr.lower() for noise in ['nav', 'menu', 'footer', 'header', 'sidebar', 'ad', 'social', 'comment', 'banner']):
                    element.decompose()

    def _extract_title_from_soup(self, soup: BeautifulSoup) -> str:
        """Extract title from soup"""
        # Try title tag first
        title_tag = soup.find('title')
        if title_tag:
            title = self._get_clean_text_from_element(title_tag).strip()
            # Clean up common patterns
            title = re.sub(r'\s*[-|]\s*.*$', '', title)
            return title
        
        # Try h1
        h1_tag = soup.find('h1')
        if h1_tag:
            return self._get_clean_text_from_element(h1_tag).strip()
        
        # Try meta title
        meta_title = soup.find('meta', property='og:title')
        if meta_title:
            return meta_title.get('content', '').strip()
        
        return ""

    def _extract_headings_from_soup(self, soup: BeautifulSoup) -> List[str]:
        """Extract headings from soup"""
        headings = []
        for level in range(1, 7):
            for heading in soup.find_all(f'h{level}'):
                text = self._get_clean_text_from_element(heading).strip()
                if text and len(text) > 3:
                    headings.append(text)
        return headings

    def _extract_paragraphs_from_soup(self, soup: BeautifulSoup) -> List[str]:
        """Extract paragraphs from soup - NEVER use get_text()"""
        paragraphs = []
        
        # Extract p tags
        for p in soup.find_all('p'):
            text = self._get_clean_text_from_element(p).strip()
            if text and len(text) > 15 and not self._is_boilerplate(text):
                paragraphs.append(text)
        
        # If no paragraphs, try divs with substantial text
        if not paragraphs:
            for div in soup.find_all('div'):
                text = self._get_clean_text_from_element(div).strip()
                if text and len(text) > 50 and not self._is_boilerplate(text):
                    # Split into sentences
                    sentences = re.split(r'[.!?]+', text)
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if sentence and len(sentence) > 15 and not self._is_boilerplate(sentence):
                            paragraphs.append(sentence)
        
        return paragraphs

    def _ensure_paragraph_structure(self, paragraphs: List[str]) -> List[str]:
        """Ensure we don't return a single merged paragraph for real pages."""
        if not paragraphs:
            return []

        # If we have multiple paragraphs already, just return.
        if len(paragraphs) > 1:
            return paragraphs

        only = (paragraphs[0] or '').strip()
        if len(only) < 250:
            return paragraphs

        # Split into sentences and group them into readable paragraphs.
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', only)
        sentences = [s.strip() for s in sentences if s and len(s.strip()) > 0]

        grouped: List[str] = []
        buf: List[str] = []
        buf_len = 0
        for s in sentences:
            if self._is_boilerplate(s):
                continue
            buf.append(s)
            buf_len += len(s)
            # flush every ~350 chars to avoid a single mega paragraph
            if buf_len >= 350:
                grouped.append(' '.join(buf).strip())
                buf = []
                buf_len = 0

        if buf:
            grouped.append(' '.join(buf).strip())

        # If splitting failed, return original
        return grouped if len(grouped) > 1 else paragraphs

    def _get_clean_text_from_element(self, element) -> str:
        """Get text from element without using get_text()"""
        if not element:
            return ""
        
        # Handle different element types
        if element.name in ['script', 'style', 'noscript']:
            return ""
        
        # Get text content properly
        text_parts = []
        
        if hasattr(element, 'string') and element.string:
            text_parts.append(element.string)
        else:
            # Extract text from children
            for child in element.children:
                if hasattr(child, 'string') and child.string:
                    text_parts.append(child.string)
                elif hasattr(child, 'children'):
                    # Recursively extract
                    child_text = self._get_clean_text_from_element(child)
                    if child_text:
                        text_parts.append(child_text)
        
        return ' '.join(text_parts)

    def _has_meaningful_content(self, element) -> bool:
        """Check if element has meaningful content"""
        if not element:
            return False
        
        # Count paragraphs
        paragraphs = element.find_all('p')
        if len(paragraphs) < 1:
            return False
        
        # Check text length
        text = self._get_clean_text_from_element(element)
        if len(text) < 50:
            return False
        
        # Check word count
        words = text.split()
        if len(words) < 10:
            return False
        
        return True

    def _is_boilerplate(self, text: str) -> bool:
        """Check if text is boilerplate"""
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in self.boilerplate_patterns)

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Fix spacing around punctuation
        text = re.sub(r'\s*([,.!?;:])\s*', r'\1 ', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        # Remove repeated punctuation
        text = re.sub(r'([,.!?;:])\1+', r'\1', text)
        
        return text

    def _validate_result(self, result: Dict) -> bool:
        """Validate extraction result"""
        if not result:
            return False
        
        # Check if we have meaningful content
        paragraphs = result.get('paragraphs', [])
        if len(paragraphs) < 1:
            return False
        
        # Check total content length
        total_text = ' '.join(paragraphs)
        if len(total_text) < 30:
            return False
        
        # Check if content is mostly boilerplate
        boilerplate_count = sum(1 for para in paragraphs if self._is_boilerplate(para))
        if boilerplate_count > len(paragraphs) * 0.7:
            return False
        
        return True
