"""
Improved Text Extractor with better content detection and cleaning
"""

import re
import logging
from typing import List, Tuple, Optional
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

class ImprovedTextExtractor:
    """Improved text extraction with scoring and cleaning."""
    
    # UI junk words to filter out
    UI_JUNK_WORDS = {
        'login', 'signin', 'sign in', 'log in', 'register', 'signup', 'sign up',
        'menu', 'navigation', 'nav', 'search', 'search...', 'password', 'username',
        'email', 'submit', 'cancel', 'close', 'ok', 'yes', 'no', 'continue',
        'back', 'next', 'previous', 'home', 'about', 'contact', 'privacy',
        'terms', 'cookies', 'settings', 'profile', 'account', 'dashboard',
        'logout', 'sign out', 'log out', 'help', 'support', 'faq', 'follow',
        'share', 'like', 'comment', 'reply', 'post', 'tweet', 'retweet',
        'subscribe', 'newsletter', 'download', 'upload', 'browse', 'filter',
        'sort', 'view more', 'show more', 'load more', 'see more', 'read more',
        'click here', 'learn more', 'find out more', 'get started', 'try now',
        'free trial', 'buy now', 'add to cart', 'checkout', 'proceed', 'pay now'
    }
    
    # Short phrases to remove (likely UI elements)
    JUNK_PHRASES = {
        'click here', 'learn more', 'read more', 'view more', 'show more',
        'find out more', 'get started', 'try now', 'sign up', 'log in',
        'contact us', 'about us', 'terms of service', 'privacy policy',
        'all rights reserved', 'copyright', '©', 'cookie policy'
    }
    
    def __init__(self, min_word_threshold: int = 10, strict_mode: bool = False):
        self.min_word_threshold = min_word_threshold
        self.strict_mode = strict_mode
        
    def extract(self, soup: BeautifulSoup) -> Tuple[str, dict]:
        """Extract text with multi-stage strategy."""
        logger.info("ImprovedTextExtractor: Starting extraction")
        
        # Stage 1: Try semantic tags
        text, strategy = self._extract_semantic_content(soup)
        if self._is_meaningful_content(text):
            logger.info("ImprovedTextExtractor: Used semantic strategy, extracted %d words", len(text.split()))
            return self._clean_text(text), {"strategy": "semantic", "word_count": len(text.split())}
        
        # Stage 2: Try largest text block
        text, strategy = self._extract_largest_block(soup)
        if self._is_meaningful_content(text):
            logger.info("ImprovedTextExtractor: Used largest block strategy, extracted %d words", len(text.split()))
            return self._clean_text(text), {"strategy": "largest_block", "word_count": len(text.split())}
        
        # Stage 3: Try paragraphs
        text, strategy = self._extract_paragraphs(soup)
        if self._is_meaningful_content(text):
            logger.info("ImprovedTextExtractor: Used paragraph strategy, extracted %d words", len(text.split()))
            return self._clean_text(text), {"strategy": "paragraphs", "word_count": len(text.split())}
        
        # Stage 4: Full page fallback
        text = soup.get_text(separator=' ', strip=True)
        logger.info("ImprovedTextExtractor: Used full page fallback, extracted %d words", len(text.split()))
        return self._clean_text(text), {"strategy": "full_page", "word_count": len(text.split())}
    
    def _extract_semantic_content(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract from semantic tags in priority order."""
        selectors = [
            'article',
            'main',
            '[role="main"]',
            'section',
            '.content',
            '.article-content',
            '.post-content',
            '.entry-content',
            '.story-body',
            '.article-body',
            '#content',
            '#main-content',
            '#article-content'
        ]
        
        best_text = ""
        best_selector = ""
        
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(separator=' ', strip=True)
                if len(text) > len(best_text):
                    best_text = text
                    best_selector = selector
        
        return best_text, best_selector or "none"
    
    def _extract_largest_block(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract the largest text block with highest density."""
        candidates = []
        
        # Check common container tags
        for tag in ['div', 'section', 'article', 'main']:
            for element in soup.find_all(tag):
                text = element.get_text(separator=' ', strip=True)
                if len(text) > 100:  # Minimum length consideration
                    density = self._calculate_text_density(element, text)
                    candidates.append((text, density, element.name))
        
        if candidates:
            # Sort by text length first, then density
            candidates.sort(key=lambda x: (len(x[0]), x[1]), reverse=True)
            return candidates[0][0], f"largest_{candidates[0][2]}"
        
        return "", "none"
    
    def _extract_paragraphs(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract all paragraph text."""
        paragraphs = soup.find_all('p')
        texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
        return ' '.join(texts), "paragraphs"
    
    def _calculate_text_density(self, element: Tag, text: str) -> float:
        """Calculate text density score."""
        if not text:
            return 0.0
        
        # Count text vs HTML ratio
        html_length = len(str(element))
        text_length = len(text)
        
        if html_length == 0:
            return 0.0
        
        # Penalize elements with many links
        links = element.find_all('a')
        link_penalty = len(links) * 0.1
        
        # Bonus for semantic tags
        tag_bonus = 0.0
        if element.name in ['article', 'main', 'section']:
            tag_bonus = 0.5
        elif element.get('class'):
            classes = ' '.join(element.get('class')).lower()
            if any(keyword in classes for keyword in ['content', 'article', 'post', 'story']):
                tag_bonus = 0.3
        
        density = (text_length / html_length) - link_penalty + tag_bonus
        return max(density, 0.0)
    
    def _is_meaningful_content(self, text: str) -> bool:
        """Check if content is meaningful."""
        if not text:
            return False
        
        words = text.split()
        word_count = len(words)
        
        # Check minimum word threshold
        if word_count < self.min_word_threshold:
            return False
        
        # In strict mode, apply more checks
        if self.strict_mode:
            # Check average word length
            avg_word_length = sum(len(word) for word in words) / word_count
            if avg_word_length < 3:  # Too many short words
                return False
            
            # Check sentence structure
            sentences = re.split(r'[.!?]+', text)
            meaningful_sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
            if len(meaningful_sentences) < 2:
                return False
        
        return True
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text from UI junk and formatting issues."""
        if not text:
            return ""
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove UI junk words (case-insensitive)
        junk_pattern = r'\b(?:' + '|'.join(re.escape(word) for word in self.UI_JUNK_WORDS) + r')\b'
        text = re.sub(junk_pattern, '', text, flags=re.IGNORECASE)
        
        # Remove junk phrases
        for phrase in self.JUNK_PHRASES:
            text = re.sub(re.escape(phrase), '', text, flags=re.IGNORECASE)
        
        # Remove repeated short phrases (likely UI elements)
        lines = text.split('\n')
        cleaned_lines = []
        seen_phrases = set()
        
        for line in lines:
            line = line.strip()
            if len(line) < 10:  # Skip very short lines
                continue
            
            # Check for repetition
            if line.lower() in seen_phrases:
                continue
            seen_phrases.add(line.lower())
            cleaned_lines.append(line)
        
        text = ' '.join(cleaned_lines)
        
        # Clean up spacing and punctuation
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'([.!?])\1+', r'\1', text)  # Remove repeated punctuation
        text = re.sub(r'\s+([.!?])', r'\1', text)   # Fix spacing before punctuation
        text = re.sub(r'([.!?])\s+', r'\1 ', text)   # Fix spacing after punctuation
        
        # Remove leading/trailing whitespace and multiple spaces
        text = text.strip()
        text = re.sub(r' +', ' ', text)
        
        return text
