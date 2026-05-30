"""
Enhanced Text Extractor Module
Improved text extraction with density scoring and better content detection.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from bs4 import BeautifulSoup, Tag
import re

@dataclass
class ContentSection:
    """A section of content with its score."""
    element: Tag
    text: str
    score: float
    word_count: int
    paragraph_count: int

class EnhancedTextExtractor:
    """Enhanced text extractor with density scoring and smart content detection."""
    
    def __init__(self):
        # Content selectors in order of preference
        self.content_selectors = [
            'article',
            'main',
            '[role="main"]',
            'section',
            '.content',
            '.article',
            '.post',
            '.main',
            '#content',
            '#main',
            '#article'
        ]
        
        # Noise patterns to remove
        self.noise_selectors = [
            'script', 'style', 'nav', 'footer', 'header', 'aside',
            '.sidebar', '.menu', '.navigation', '.ads', '.advertisement',
            '.social', '.share', '.comments', '.related', '.footer'
        ]
        
        # Low-quality content indicators
        self.low_quality_patterns = [
            r'^\s*$',
            r'©\s*\d{4}',
            r'all rights reserved',
            r'privacy policy',
            r'terms of service',
            r'cookie policy',
            r'subscribe',
            r'login',
            r'register',
            r'click here',
            r'read more'
        ]
    
    def extract(self, soup: BeautifulSoup, url: str = "") -> Tuple[str, dict]:
        """
        Extract the main content from the page.
        
        Returns:
            Tuple of (extracted_text, metadata_dict)
        """
        # Clean the soup
        self._clean_soup(soup)
        
        # Find content sections
        content_sections = self._find_content_sections(soup)
        
        if not content_sections:
            # Fallback to body text
            text = self._extract_fallback_text(soup)
            metadata = {
                "method": "fallback",
                "sections_found": 0,
                "quality_score": 0.3
            }
        else:
            # Select best section
            best_section = max(content_sections, key=lambda x: x.score)
            text = best_section.text
            metadata = {
                "method": "density_scoring",
                "sections_found": len(content_sections),
                "quality_score": best_section.score,
                "selected_element": best_section.element.name
            }
        
        # Clean and validate the text
        cleaned_text = self._clean_text(text)
        quality_info = self._validate_quality(cleaned_text)
        
        metadata.update(quality_info)
        
        return cleaned_text, metadata
    
    def _clean_soup(self, soup: BeautifulSoup) -> None:
        """Remove noise elements from the soup."""
        # Remove noise elements
        for selector in self.noise_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        # Remove elements with common noise classes
        noise_classes = ['ad', 'advertisement', 'banner', 'popup', 'modal']
        for class_name in noise_classes:
            for element in soup.find_all(class_=lambda x: x and class_name in str(x).lower()):
                element.decompose()
    
    def _find_content_sections(self, soup: BeautifulSoup) -> List[ContentSection]:
        """Find potential content sections and score them."""
        sections = []
        
        # Try specific selectors first
        for selector in self.content_selectors:
            elements = soup.select(selector)
            for element in elements:
                section = self._create_content_section(element)
                if section and section.word_count > 10:  # Minimum content threshold
                    sections.append(section)
        
        # If no good sections found, try common containers
        if not sections:
            for tag in ['div', 'section']:
                for element in soup.find_all(tag):
                    section = self._create_content_section(element)
                    if section and section.word_count > 20:
                        sections.append(section)
        
        return sections
    
    def _create_content_section(self, element: Tag) -> Optional[ContentSection]:
        """Create a ContentSection from an element."""
        # Extract text from this element
        text = element.get_text(separator=' ', strip=True)
        
        if not text or len(text) < 50:
            return None
        
        # Count paragraphs and words
        paragraphs = element.find_all('p')
        paragraph_count = len(paragraphs)
        word_count = len(text.split())
        
        # Calculate density score
        score = self._calculate_density_score(element, text, paragraph_count, word_count)
        
        return ContentSection(
            element=element,
            text=text,
            score=score,
            word_count=word_count,
            paragraph_count=paragraph_count
        )
    
    def _calculate_density_score(self, element: Tag, text: str, 
                               paragraph_count: int, word_count: int) -> float:
        """Calculate content density score for an element."""
        score = 0.0
        
        # Base score from word count
        if word_count > 100:
            score += 2.0
        elif word_count > 50:
            score += 1.0
        
        # Paragraph density
        if paragraph_count > 5:
            score += 1.5
        elif paragraph_count > 2:
            score += 1.0
        
        # Text to HTML ratio (higher is better)
        html_length = len(str(element))
        if html_length > 0:
            text_ratio = len(text) / html_length
            score += text_ratio * 2.0
        
        # Element type bonus
        tag_name = element.name.lower()
        if tag_name == 'article':
            score += 3.0
        elif tag_name == 'main':
            score += 2.5
        elif tag_name == 'section':
            score += 1.5
        elif tag_name == 'div':
            score += 0.5
        
        # Class/ID bonus
        class_id = f"{element.get('class', '')} {element.get('id', '')}".lower()
        content_keywords = ['content', 'article', 'post', 'main', 'story', 'text']
        for keyword in content_keywords:
            if keyword in class_id:
                score += 1.0
        
        # Heading presence (good content structure)
        headings = element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if len(headings) >= 2:
            score += 1.0
        
        # Link density penalty (too many links might be navigation)
        links = element.find_all('a')
        if word_count > 0:
            link_ratio = len(links) / word_count
            if link_ratio > 0.3:  # More than 1 link per 3 words
                score -= 1.0
        
        return max(score, 0.0)
    
    def _extract_fallback_text(self, soup: BeautifulSoup) -> str:
        """Extract text as a fallback when no good sections are found."""
        # Try to get all paragraphs
        paragraphs = soup.find_all('p')
        if paragraphs:
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            return ' '.join(texts)
        
        # Fallback to body text
        return soup.get_text(separator=' ', strip=True)
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize the extracted text."""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove common boilerplate
        for pattern in self.low_quality_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove multiple consecutive punctuation
        text = re.sub(r'([.!?])\1+', r'\1', text)
        
        # Clean up spacing around punctuation
        text = re.sub(r'\s+([.!?])', r'\1', text)
        text = re.sub(r'([.!?])\s+', r'\1 ', text)
        
        return text.strip()
    
    def _validate_quality(self, text: str) -> dict:
        """Validate the quality of extracted text."""
        word_count = len(text.split()) if text else 0
        char_count = len(text) if text else 0
        
        # Quality indicators
        quality_issues = []
        
        if word_count < 50:
            quality_issues.append("Very low word count")
        elif word_count < 100:
            quality_issues.append("Low word count")
        
        if char_count < 200:
            quality_issues.append("Very short content")
        
        # Check for repetitive content
        sentences = text.split('. ')
        if len(sentences) > 10:
            unique_sentences = set(sentences)
            if len(unique_sentences) < len(sentences) * 0.7:
                quality_issues.append("Repetitive content detected")
        
        # Check for meaningful content (has some longer sentences)
        long_sentences = [s for s in sentences if len(s.split()) > 10]
        if not long_sentences and word_count > 50:
            quality_issues.append("Content lacks depth")
        
        # Overall quality score
        quality_score = 1.0
        for issue in quality_issues:
            quality_score -= 0.2
        
        quality_score = max(quality_score, 0.0)
        
        return {
            "word_count": word_count,
            "char_count": char_count,
            "sentence_count": len(sentences),
            "quality_score": quality_score,
            "quality_issues": quality_issues,
            "is_high_quality": quality_score >= 0.7
        }
