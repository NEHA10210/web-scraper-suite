"""
Professional Content Extraction Engine
Uses Readability algorithm and proper content extraction techniques
"""

from readability import Document
from newspaper import Article
from bs4 import BeautifulSoup, Comment
import re
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ExtractedContent:
    """Structured content extraction result"""
    title: str
    headings: List[str]
    paragraphs: List[str]
    url: str
    success: bool = True
    error: Optional[str] = None

class ContentExtractor:
    """
    Professional content extraction engine using Readability algorithm
    """
    
    def __init__(self):
        self.noise_selectors = [
            # Navigation and menus
            'nav', 'menu', 'navbar', 'navigation', 'nav-menu', 'main-menu',
            '.nav', '.menu', '.navbar', '.navigation', '.nav-menu', '.main-menu',
            '#nav', '#menu', '#navbar', '#navigation', '#nav-menu', '#main-menu',
            
            # Headers and footers
            'header', 'footer', '.header', '.footer', '#header', '#footer',
            '.site-header', '.site-footer', '#site-header', '#site-footer',
            
            # Sidebars and widgets
            'aside', 'sidebar', '.sidebar', '.aside', '#sidebar', '#aside',
            '.widget', '.widgets', '#widget', '#widgets',
            
            # Ads and promotions
            'ad', 'ads', 'advertisement', '.ad', '.ads', '.advertisement',
            '#ad', '#ads', '#advertisement', '.banner', '.promo', '.promotion',
            
            # Social and sharing
            'social', '.social', '#social', '.share', '.sharing', '#share',
            '.follow', '.follow-us', '.subscribe', '.newsletter',
            
            # Comments and interactions
            'comments', '.comments', '#comments', '.comment', '.reply',
            '.discussion', '.feedback',
            
            # Forms and buttons
            'form', 'button', 'input', 'select', 'textarea', '.form',
            'button', '.button', 'btn', '.btn', '#btn',
            
            # Scripts and styles
            'script', 'style', 'noscript', 'link[rel="stylesheet"]',
            
            # Common noise patterns
            '.popup', '.modal', '.overlay', '.cookie', '.cookie-notice',
            '.breadcrumb', '.breadcrumbs', '.pagination', '.pager',
            
            # Specific common IDs/classes
            '[class*="nav"]', '[class*="menu"]', '[class*="sidebar"]',
            '[class*="ad"]', '[class*="social"]', '[class*="comment"]',
            '[class*="footer"]', '[class*="header"]', '[id*="nav"]',
            '[id*="menu"]', '[id*="sidebar"]', '[id*="ad"]', '[id*="social"]',
            '[id*="comment"]', '[id*="footer"]', '[id*="header"]'
        ]
        
        self.boilerplate_patterns = [
            r'skip to main content',
            r'sign up', r'sign in', r'log in', r'login', r'register',
            r'try now', r'get started', r'learn more', r'read more',
            r'click here', r'follow us', r'subscribe', r'newsletter',
            r'privacy policy', r'terms of service', r'cookie policy',
            r'all rights reserved', r'copyright', r'\d{4}.*all rights',
            r'contact us', r'about us', r'help', r'support',
            r'share this', r'like this', r'tweet this', r'facebook',
            r'twitter', r'instagram', r'linkedin', r'youtube',
            r'back to top', r'return to top', r'jump to navigation'
        ]

    def extract_content(self, html: str, url: str) -> ExtractedContent:
        """
        Extract clean content using Readability algorithm
        
        Args:
            html: Raw HTML content
            url: Source URL
            
        Returns:
            ExtractedContent with structured clean content
        """
        try:
            # Method 1: Try Readability algorithm first (preferred)
            content = self._extract_with_readability(html, url)
            if content and self._validate_content(content):
                logger.info("Successfully extracted content with Readability algorithm")
                return content
            
            # Method 2: Fallback to Newspaper extraction
            content = self._extract_with_newspaper(html, url)
            if content and self._validate_content(content):
                logger.info("Successfully extracted content with Newspaper")
                return content
            
            # Method 3: Last resort - custom heuristic extraction
            content = self._extract_with_heuristics(html, url)
            if content and len(content.paragraphs) > 0:  # Relaxed validation
                logger.info("Successfully extracted content with heuristics")
                return content
            
            # If all methods fail
            return ExtractedContent(
                title="",
                headings=[],
                paragraphs=[],
                url=url,
                success=False,
                error="Could not extract readable content from the page"
            )
            
        except Exception as e:
            logger.error(f"Content extraction failed: {str(e)}")
            return ExtractedContent(
                title="",
                headings=[],
                paragraphs=[],
                url=url,
                success=False,
                error=f"Extraction error: {str(e)}"
            )

    def _extract_with_readability(self, html: str, url: str) -> Optional[ExtractedContent]:
        """Extract content using Mozilla Readability algorithm"""
        try:
            # Create Readability document
            doc = Document(html, url=url)
            
            # Get the cleaned HTML
            clean_html = doc.summary()
            
            # Parse cleaned HTML
            soup = BeautifulSoup(clean_html, 'html.parser')
            
            # Extract title
            title = doc.title() or self._extract_title_from_soup(soup)
            
            # Extract headings
            headings = self._extract_headings_from_soup(soup)
            
            # Extract paragraphs (NEVER use get_text())
            paragraphs = self._extract_paragraphs_from_soup(soup)
            
            return ExtractedContent(
                title=self._clean_text(title),
                headings=[self._clean_text(h) for h in headings],
                paragraphs=[self._clean_text(p) for p in paragraphs if p.strip()],
                url=url
            )
            
        except Exception as e:
            logger.warning(f"Readability extraction failed: {str(e)}")
            return None

    def _extract_with_newspaper(self, html: str, url: str) -> Optional[ExtractedContent]:
        """Extract content using Newspaper3k library"""
        try:
            # Create Article object
            article = Article(url)
            article.html = html
            
            # Parse the article
            article.parse()
            
            # Extract content
            title = article.title or ""
            
            # Parse HTML for structure
            soup = BeautifulSoup(article.html, 'html.parser')
            
            # Extract headings and paragraphs
            headings = self._extract_headings_from_soup(soup)
            paragraphs = self._extract_paragraphs_from_soup(soup)
            
            # If newspaper didn't extract good content, use its text but split into paragraphs
            if not paragraphs and article.text:
                paragraphs = self._split_text_to_paragraphs(article.text)
            
            return ExtractedContent(
                title=self._clean_text(title),
                headings=[self._clean_text(h) for h in headings],
                paragraphs=[self._clean_text(p) for p in paragraphs if p.strip()],
                url=url
            )
            
        except Exception as e:
            logger.warning(f"Newspaper extraction failed: {str(e)}")
            return None

    def _extract_with_heuristics(self, html: str, url: str) -> Optional[ExtractedContent]:
        """Extract content using custom heuristic approach"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove noise elements
            self._remove_noise_elements(soup)
            
            # Find main content area
            main_content = self._find_main_content_heuristic(soup)
            
            if not main_content:
                main_content = soup.find('body') or soup
            
            # Extract title
            title = self._extract_title_from_soup(soup)
            
            # Extract headings and paragraphs
            headings = self._extract_headings_from_soup(main_content)
            paragraphs = self._extract_paragraphs_from_soup(main_content)
            
            # If still no paragraphs, try a more aggressive approach
            if not paragraphs:
                paragraphs = self._extract_paragraphs_aggressive(main_content)
            
            return ExtractedContent(
                title=self._clean_text(title),
                headings=[self._clean_text(h) for h in headings],
                paragraphs=[self._clean_text(p) for p in paragraphs if p.strip()],
                url=url
            )
            
        except Exception as e:
            logger.warning(f"Heuristic extraction failed: {str(e)}")
            return None

    def _remove_noise_elements(self, soup: BeautifulSoup):
        """Remove noise elements from the DOM"""
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
        
        # Remove elements with boilerplate class names
        for element in soup.find_all():
            if element and hasattr(element, 'attrs'):
                class_attr = element.attrs.get('class', [])
                id_attr = element.attrs.get('id', '')
                
                # Check class names
                if class_attr:
                    class_str = ' '.join(class_attr).lower()
                    if any(pattern in class_str for pattern in ['ad', 'social', 'comment', 'footer', 'header', 'nav', 'menu']):
                        element.decompose()
                        continue
                
                # Check ID
                if id_attr and any(pattern in id_attr.lower() for pattern in ['ad', 'social', 'comment', 'footer', 'header', 'nav', 'menu']):
                    element.decompose()

    def _find_main_content_heuristic(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Find main content using heuristic approach"""
        # Try semantic HTML5 tags first
        for tag in ['main', 'article', 'section[role="main"]']:
            element = soup.select_one(tag)
            if element and self._has_sufficient_content(element):
                return element
        
        # Try common content containers
        content_selectors = [
            '.content', '.post-content', '.entry-content', '.article-content',
            '.story-content', '.main-content', '.page-content', '.post-body',
            '.article-body', '.story-body', '#content', '#main-content',
            '.post', '.article', '.story'
        ]
        
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element and self._has_sufficient_content(element):
                return element
        
        # Find element with most text content
        candidates = []
        for element in soup.find_all(['div', 'section', 'article']):
            if self._has_sufficient_content(element):
                text_length = len(self._extract_text_from_element(element))
                paragraph_count = len(element.find_all('p'))
                score = text_length + (paragraph_count * 100)
                candidates.append((element, score))
        
        if candidates:
            return max(candidates, key=lambda x: x[1])[0]
        
        return None

    def _has_sufficient_content(self, element) -> bool:
        """Check if element has sufficient content to be main content"""
        if not element:
            return False
        
        # Count paragraphs
        paragraphs = element.find_all('p')
        if len(paragraphs) < 2:
            return False
        
        # Check text length
        text = self._extract_text_from_element(element)
        if len(text) < 200:
            return False
        
        # Check text quality (ratio of actual content)
        words = text.split()
        if len(words) < 50:
            return False
        
        return True

    def _extract_title_from_soup(self, soup: BeautifulSoup) -> str:
        """Extract title from soup"""
        # Try title tag first
        title_tag = soup.find('title')
        if title_tag:
            title = self._extract_text_from_element(title_tag).strip()
            # Clean up common patterns
            title = re.sub(r'\s*[-|]\s*.*$', '', title)  # Remove site name
            return title
        
        # Try h1
        h1_tag = soup.find('h1')
        if h1_tag:
            return self._extract_text_from_element(h1_tag).strip()
        
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
                text = self._extract_text_from_element(heading).strip()
                if text and len(text) > 3:  # Skip very short headings
                    headings.append(text)
        return headings

    def _extract_paragraphs_from_soup(self, soup: BeautifulSoup) -> List[str]:
        """Extract paragraphs from soup - NEVER use get_text()"""
        paragraphs = []
        
        # Extract p tags
        for p in soup.find_all('p'):
            text = self._extract_text_from_element(p).strip()
            if text and len(text) > 20:  # Skip very short paragraphs
                # Filter out boilerplate
                if not self._is_boilerplate(text):
                    paragraphs.append(text)
        
        # If no paragraphs, try to extract from divs with text content
        if not paragraphs:
            for div in soup.find_all('div'):
                text = self._extract_text_from_element(div).strip()
                if text and len(text) > 100:
                    # Split into sentences and treat as paragraphs
                    sentences = re.split(r'[.!?]+', text)
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if sentence and len(sentence) > 20 and not self._is_boilerplate(sentence):
                            paragraphs.append(sentence)
        
        return paragraphs

    def _extract_text_from_element(self, element) -> str:
        """Extract text from element without using get_text()"""
        if not element:
            return ""
        
        # Handle different element types
        if element.name in ['script', 'style', 'noscript']:
            return ""
        
        # Get text from element and its children
        text_parts = []
        
        if element.string:
            # Element has direct text
            text_parts.append(element.string)
        else:
            # Element has children - extract text from each child
            for child in element.children:
                if hasattr(child, 'string') and child.string:
                    text_parts.append(child.string)
                elif hasattr(child, 'children'):
                    # Recursively extract from nested elements
                    child_text = self._extract_text_from_element(child)
                    if child_text:
                        text_parts.append(child_text)
        
        return ' '.join(text_parts)

    def _split_text_to_paragraphs(self, text: str) -> List[str]:
        """Split plain text into paragraphs"""
        # Split by double newlines or sentences
        paragraphs = re.split(r'\n\s*\n|[.!?]+(?=\s+[A-Z])', text)
        
        # Clean and filter
        clean_paragraphs = []
        for para in paragraphs:
            para = para.strip()
            if para and len(para) > 20 and not self._is_boilerplate(para):
                clean_paragraphs.append(para)
        
        return clean_paragraphs

    def _is_boilerplate(self, text: str) -> bool:
        """Check if text is boilerplate/noise"""
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

    def _extract_paragraphs_aggressive(self, soup: BeautifulSoup) -> List[str]:
        """Extract paragraphs using aggressive approach"""
        paragraphs = []
        
        # Try all text nodes and split into meaningful chunks
        try:
            all_text = '\n'.join([str(s) for s in soup.stripped_strings])
        except Exception:
            all_text = ''
        
        if all_text:
            # Split by double newlines or sentences
            chunks = re.split(r'\n\s*\n|[.!?]+(?=\s+[A-Z])', all_text)
            
            for chunk in chunks:
                chunk = chunk.strip()
                if chunk and len(chunk) > 20 and not self._is_boilerplate(chunk):
                    # Further split if too long
                    if len(chunk) > 300:
                        sentences = re.split(r'[.!?]+', chunk)
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if sentence and len(sentence) > 15:
                                paragraphs.append(sentence)
                    else:
                        paragraphs.append(chunk)
        
        return paragraphs

    def _validate_content(self, content: ExtractedContent) -> bool:
        """Validate extracted content quality"""
        if not content or not content.success:
            return False
        
        # Check if we have meaningful content
        if not content.paragraphs or len(content.paragraphs) == 0:
            return False
        
        # Check total content length
        total_text = ' '.join(content.paragraphs)
        if len(total_text) < 100:
            return False
        
        # Check if content is mostly boilerplate
        boilerplate_count = sum(1 for para in content.paragraphs if self._is_boilerplate(para))
        if boilerplate_count > len(content.paragraphs) * 0.5:
            return False
        
        return True
