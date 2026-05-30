"""
Advanced Text Processing Pipeline with NLP
Clean text extraction, content analysis, and structured output
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncio
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin
import spacy
from collections import Counter
import hashlib
from textstat import flesch_reading_ease, flesch_kincaid_grade
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class ProcessedContent:
    title: str
    headings: List[Dict[str, Any]]
    paragraphs: List[str]
    lists: List[Dict[str, Any]]
    keywords: List[Dict[str, Any]]
    entities: List[Dict[str, Any]]
    summary: Dict[str, str]
    readability: Dict[str, Any]
    seo: Dict[str, Any]
    classification: Dict[str, Any]
    metadata: Dict[str, Any]

class AdvancedTextProcessor:
    def __init__(self):
        # Load spaCy model for NLP
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spaCy model not found. Install with: python -m spacy download en_core_web_sm")
            self.nlp = None
        
        # Content extraction patterns
        self.content_selectors = [
            'article', 'main', '[role="main"]', '.content', '.post-content',
            '.entry-content', '.article-body', '.story-body', '.post-body',
            '#content', '#main', '.main-content', '.container .row'
        ]
        
        # Noise patterns to remove
        self.noise_selectors = [
            'nav', 'header', 'footer', '.nav', '.navigation', '.menu',
            '.sidebar', '.widget', '.ads', '.advertisement', '.social',
            '.comments', '.footer', '.header', '.breadcrumb', '.pagination'
        ]
        
        # Boilerplate text patterns
        self.boilerplate_patterns = [
            r'click here', r'read more', r'learn more', r'subscribe now',
            r'follow us', r'contact us', r'privacy policy', r'terms of service',
            r'all rights reserved', r'copyright', r'\d{4}.*all rights',
            r'cookie policy', r'accept cookies', r'website uses cookies'
        ]
        
        # Classification keywords
        self.classification_keywords = {
            'blog': ['blog', 'post', 'article', 'published', 'author', 'comments'],
            'ecommerce': ['price', 'cart', 'buy', 'shop', 'product', 'add to cart', 'wishlist'],
            'documentation': ['documentation', 'api', 'reference', 'guide', 'tutorial', 'example'],
            'landing': ['sign up', 'register', 'start free', 'get started', 'trial', 'demo'],
            'news': ['news', 'breaking', 'report', 'journalist', 'published', 'updated']
        }
    
    def process_html(self, html: str, url: str = "") -> ProcessedContent:
        """Main processing pipeline"""
        try:
            soup = BeautifulSoup(html, 'lxml')
            
            # Clean and extract content
            clean_soup = self._clean_html(soup)
            main_content = self._extract_main_content(clean_soup)
            
            # Extract structured content
            title = self._extract_title(main_content)
            headings = self._extract_headings(main_content)
            paragraphs = self._extract_paragraphs(main_content)
            lists = self._extract_lists(main_content)
            
            # NLP Analysis
            keywords = self._extract_keywords(paragraphs)
            entities = self._extract_entities(paragraphs) if self.nlp else []
            summary = self._generate_summary(paragraphs)
            
            # Readability metrics
            readability = self._calculate_readability(paragraphs)
            
            # SEO analysis
            seo = self._analyze_seo(soup, title, paragraphs)
            
            # Content classification
            classification = self._classify_content(title, paragraphs, url)
            
            # Metadata
            metadata = self._extract_metadata(soup, url)
            
            return ProcessedContent(
                title=title,
                headings=headings,
                paragraphs=paragraphs,
                lists=lists,
                keywords=keywords,
                entities=entities,
                summary=summary,
                readability=readability,
                seo=seo,
                classification=classification,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Error processing HTML: {str(e)}")
            raise
    
    def _clean_html(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove noise and clean HTML"""
        # Make a copy to avoid modifying original
        clean_soup = BeautifulSoup(str(soup), 'lxml')
        
        # Remove noise elements
        for selector in self.noise_selectors:
            for element in clean_soup.select(selector):
                element.decompose()
        
        # Remove elements with common noise classes
        noise_classes = ['ad', 'ads', 'advertisement', 'banner', 'popup', 'modal', 'overlay']
        for class_name in noise_classes:
            for element in clean_soup.find_all(class_=lambda x: x and any(noise in str(x).lower() for noise in noise_classes)):
                element.decompose()
        
        # Remove scripts, styles, and comments
        for element in clean_soup(['script', 'style', 'noscript']):
            element.decompose()
        
        # Remove HTML comments
        from bs4 import Comment
        for comment in clean_soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove empty elements
        for element in clean_soup.find_all():
            if not self._text_from_element(element, strip=True) and not element.find('img'):
                element.decompose()
        
        return clean_soup
    
    def _extract_main_content(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Extract the main content area using Readability-like algorithm"""
        # Remove all unwanted elements first
        self._remove_unwanted_elements(soup)
        
        # Try to find main content using multiple strategies
        main_content = None
        
        # Strategy 1: Look for semantic HTML5 tags
        for selector in ['main', 'article', '[role="main"]']:
            element = soup.select_one(selector)
            if element and self._is_likely_main_content(element):
                main_content = element
                break
        
        # Strategy 2: Look for common content containers
        if not main_content:
            content_selectors = [
                '.content', '.post-content', '.entry-content', '.article-content',
                '.story-content', '.main-content', '.page-content', '.post-body',
                '.article-body', '.story-body', '#content', '#main-content',
                '.container .row .col', '.row .col-lg-8', '.row .col-md-8'
            ]
            
            for selector in content_selectors:
                element = soup.select_one(selector)
                if element and self._is_likely_main_content(element):
                    main_content = element
                    break
        
        # Strategy 3: Use readability algorithm - find the element with most text content
        if not main_content:
            main_content = self._find_content_by_density(soup)
        
        # Strategy 4: Last resort - use body but clean it
        if not main_content:
            main_content = soup.find('body') or soup
        
        # Final cleaning of the main content
        self._clean_main_content(main_content)
        
        return main_content
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup):
        """Remove clearly unwanted elements"""
        unwanted_selectors = [
            'nav', 'header', 'footer', 'aside', '.nav', '.navigation', '.menu',
            '.sidebar', '.widget', '.ads', '.advertisement', '.ad', '.banner',
            '.social', '.comments', '.comment', '.footer', '.header', '.breadcrumb',
            '.pagination', '.popup', '.modal', '.overlay', '.cookie', '.newsletter',
            '.subscribe', '.share', '.related', '.recommended', '.trending',
            'script', 'style', 'noscript', 'iframe', 'embed', 'object'
        ]
        
        for selector in unwanted_selectors:
            for element in soup.select(selector):
                if element:
                    element.decompose()
        
        # Remove elements with unwanted classes
        unwanted_classes = [
            'ad', 'ads', 'advertisement', 'banner', 'popup', 'modal', 'overlay',
            'social', 'share', 'comment', 'footer', 'header', 'nav', 'sidebar',
            'widget', 'related', 'recommended', 'trending', 'newsletter', 'subscribe'
        ]
        
        for element in soup.find_all():
            if element and hasattr(element, 'attrs') and element.attrs:
                classes = element.attrs.get('class', [])
                if classes and any(any(unwanted in str(class_name).lower() for unwanted in unwanted_classes) 
                      for class_name in classes):
                    element.decompose()
        
        # Remove HTML comments
        from bs4 import Comment
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
    
    def _is_likely_main_content(self, element) -> bool:
        """Check if element is likely to contain main content"""
        if not element:
            return False
        
        text = self._text_from_element(element, strip=True)
        if len(text) < 100:  # Too short to be main content
            return False
        
        # Check for content indicators
        text_lower = text.lower()
        content_indicators = ['article', 'post', 'content', 'story', 'blog', 'news']
        
        # Check element's own attributes
        element_str = str(element).lower()
        if any(indicator in element_str for indicator in content_indicators):
            return True
        
        # Check text quality (ratio of meaningful words)
        words = text.split()
        if len(words) < 20:
            return False
        
        # Check if it contains paragraphs
        paragraphs = element.find_all('p')
        if len(paragraphs) >= 2:
            return True
        
        # Check text density
        total_length = len(str(element))
        text_length = len(text)
        if total_length > 0 and text_length / total_length > 0.3:
            return True
        
        return False
    
    def _find_content_by_density(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Find main content by text density"""
        candidates = []
        
        # Look at common container elements
        for element in soup.find_all(['div', 'section', 'article', 'main']):
            text = self._text_from_element(element, strip=True)
            if len(text) < 200:  # Skip very short elements
                continue
            
            # Calculate content score
            word_count = len(text.split())
            paragraph_count = len(element.find_all('p'))
            heading_count = len(element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            
            # Skip if no paragraphs
            if paragraph_count == 0:
                continue
            
            # Calculate density score
            score = (word_count * 0.3) + (paragraph_count * 10) + (heading_count * 5)
            
            # Penalty for too many links (likely navigation)
            link_count = len(element.find_all('a'))
            if link_count > word_count / 10:
                score *= 0.5
            
            candidates.append((element, score))
        
        if candidates:
            # Return the element with highest score
            return max(candidates, key=lambda x: x[1])[0]
        
        return soup.find('body') or soup
    
    def _clean_main_content(self, element):
        """Clean the main content element"""
        # Remove empty elements
        for child in element.find_all():
            if not self._text_from_element(child, strip=True) and not child.find('img'):
                child.decompose()
        
        # Remove elements with very little text
        for child in element.find_all():
            text = self._text_from_element(child, strip=True)
            if len(text) < 10 and child.name not in ['img', 'br', 'hr']:
                child.decompose()
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract the main title"""
        # Try title tag first
        title_tag = soup.find('title')
        if title_tag:
            title = self._text_from_element(title_tag, strip=True)
            # Remove site name from title
            if '|' in title:
                title = title.split('|')[0].strip()
            elif '-' in title:
                title = title.split('-')[0].strip()
            return title
        
        # Try h1
        h1 = soup.find('h1')
        if h1:
            return self._text_from_element(h1, strip=True)
        
        # Try other heading tags
        for tag in ['h2', 'h3']:
            heading = soup.find(tag)
            if heading:
                return self._text_from_element(heading, strip=True)
        
        return "Untitled"
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all headings with hierarchy"""
        headings = []
        
        for level in range(1, 7):
            for heading in soup.find_all(f'h{level}'):
                text = self._text_from_element(heading, strip=True)
                if text and len(text) > 3:  # Filter out very short headings
                    headings.append({
                        'level': level,
                        'text': text,
                        'id': heading.get('id', ''),
                        'class': heading.get('class', []),
                        'anchor': self._create_anchor(text)
                    })
        
        return headings
    
    def _extract_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        """Extract clean paragraphs with duplicate removal"""
        paragraphs = []
        
        for p in soup.find_all('p'):
            text = self._clean_text(self._text_from_element(p))
            if text and len(text) > 20:  # Filter out very short paragraphs
                paragraphs.append(text)
        
        # Remove duplicates and noise
        cleaned_paragraphs = self._remove_duplicates_and_noise(paragraphs)
        
        return cleaned_paragraphs
    
    def _extract_lists(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract structured lists"""
        lists = []
        
        for list_tag in soup.find_all(['ul', 'ol']):
            items = []
            for li in list_tag.find_all('li'):
                text = self._clean_text(self._text_from_element(li))
                if text:
                    items.append(text)
            
            if items:
                lists.append({
                    'type': list_tag.name,
                    'class': list_tag.get('class', []),
                    'items': items
                })
        
        return lists

    def _text_from_element(self, el, strip: bool = False) -> str:
        """Extract text from a BeautifulSoup element without using get_text()."""
        if not el:
            return ''
        try:
            text = ' '.join([str(s) for s in el.stripped_strings])
        except Exception:
            text = ''
        return text.strip() if strip else text
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text with advanced whitespace handling"""
        if not text:
            return ""
        
        # Remove HTML entities and decode
        import html
        text = html.unescape(text)
        
        # Fix common spacing issues
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        
        # Fix spacing around punctuation
        text = re.sub(r'\s*([,.!?;:])\s*', r'\1 ', text)
        text = re.sub(r'\s*([()\[\]{}])\s*', r' \1 ', text)
        
        # Fix merged words (add space between camelCase and number transitions)
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        text = re.sub(r'([A-Za-z])(\d)', r'\1 \2', text)
        text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)
        
        # Remove extra whitespace at beginning/end of lines
        text = re.sub(r'^\s+|\s+$', '', text, flags=re.MULTILINE)
        
        # Replace multiple newlines with single newline
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        # Fix repeated punctuation
        text = re.sub(r'([,.!?;:])\1+', r'\1', text)
        
        # Remove special characters but keep important punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\{\}\"\'\/\n]', ' ', text)
        
        # Final cleanup - remove any remaining multiple spaces
        text = re.sub(r' +', ' ', text)
        
        # Fix spacing after punctuation one more time
        text = re.sub(r'([,.!?;:])(?=\S)', r'\1 ', text)
        
        return text.strip()
    
    def _remove_duplicates_and_noise(self, paragraphs: List[str]) -> List[str]:
        """Remove duplicate paragraphs and noisy content"""
        if not paragraphs:
            return []
        
        cleaned_paragraphs = []
        seen_texts = set()
        
        # Common boilerplate patterns to detect
        boilerplate_patterns = [
            r'click here', r'read more', r'learn more', r'subscribe now',
            r'follow us', r'contact us', r'privacy policy', r'terms of service',
            r'all rights reserved', r'copyright', r'\d{4}.*all rights',
            r'cookie policy', r'accept cookies', r'website uses cookies',
            r'by continuing', r'this website uses', r'we use cookies',
            r'share this', r'like this', r'tweet this', r'facebook',
            r'twitter', r'instagram', r'linkedin', r'social media',
            r'newsletter', r'sign up', r'join our', r'get updates'
        ]
        
        for paragraph in paragraphs:
            # Skip very short paragraphs
            if len(paragraph.strip()) < 20:
                continue
            
            # Skip if it matches boilerplate patterns
            if any(re.search(pattern, paragraph, re.IGNORECASE) for pattern in boilerplate_patterns):
                continue
            
            # Skip if mostly punctuation or numbers
            text_chars = len(re.sub(r'[^a-zA-Z]', '', paragraph))
            if text_chars < len(paragraph) * 0.3:  # Less than 30% letters
                continue
            
            # Skip duplicates (using simple hash)
            paragraph_hash = hash(paragraph.lower().strip())
            if paragraph_hash in seen_texts:
                continue
            
            seen_texts.add(paragraph_hash)
            cleaned_paragraphs.append(paragraph.strip())
        
        return cleaned_paragraphs
    
    def _extract_keywords(self, paragraphs: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """Extract keywords using TF-IDF"""
        if not paragraphs:
            return []
        
        # Combine all text
        text = ' '.join(paragraphs)
        
        # Simple keyword extraction using frequency
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        word_freq = Counter(words)
        
        # Remove common stop words
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'doesnt', 'let', 'put', 'say', 'she', 'too', 'use'}
        
        for stop_word in stop_words:
            if stop_word in word_freq:
                del word_freq[stop_word]
        
        # Get top keywords
        top_keywords = word_freq.most_common(top_k)
        
        return [
            {
                'keyword': keyword,
                'frequency': freq,
                'density': round((freq / len(words)) * 100, 2)
            }
            for keyword, freq in top_keywords
        ]
    
    def _extract_entities(self, paragraphs: List[str]) -> List[Dict[str, Any]]:
        """Extract named entities using spaCy"""
        if not self.nlp or not paragraphs:
            return []
        
        text = ' '.join(paragraphs)
        doc = self.nlp(text)
        
        entities = []
        for ent in doc.ents:
            if ent.label_ in ['PERSON', 'ORG', 'GPE', 'PRODUCT', 'EVENT']:
                entities.append({
                    'text': ent.text,
                    'label': ent.label_,
                    'description': spacy.explain(ent.label_) if hasattr(spacy, 'explain') else ent.label_,
                    'start': ent.start_char,
                    'end': ent.end_char
                })
        
        # Remove duplicates and sort by frequency
        unique_entities = {}
        for entity in entities:
            key = f"{entity['text'].lower()}_{entity['label']}"
            if key not in unique_entities:
                unique_entities[key] = entity
                unique_entities[key]['count'] = 1
            else:
                unique_entities[key]['count'] += 1
        
        return sorted(unique_entities.values(), key=lambda x: x['count'], reverse=True)
    
    def _generate_summary(self, paragraphs: List[str]) -> Dict[str, str]:
        """Generate short and long summaries"""
        if not paragraphs:
            return {'short': '', 'long': ''}
        
        # Short summary (first paragraph or first 2 sentences)
        first_para = paragraphs[0] if paragraphs else ""
        sentences = re.split(r'[.!?]+', first_para)
        short_summary = '. '.join(sentences[:2]).strip()
        
        # Long summary (first 3 paragraphs or first 5 sentences)
        long_text = '. '.join(paragraphs[:3])
        long_sentences = re.split(r'[.!?]+', long_text)
        long_summary = '. '.join(long_sentences[:5]).strip()
        
        return {
            'short': short_summary,
            'long': long_summary
        }
    
    def _calculate_readability(self, paragraphs: List[str]) -> Dict[str, Any]:
        """Calculate readability metrics"""
        if not paragraphs:
            return {
                'reading_time': 0,
                'flesch_score': 0,
                'grade_level': 0,
                'avg_sentence_length': 0,
                'total_words': 0,
                'total_sentences': 0
            }
        
        text = ' '.join(paragraphs)
        
        # Basic metrics
        words = text.split()
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        
        total_words = len(words)
        total_sentences = len(sentences)
        
        # Reading time (average 200 words per minute)
        reading_time = max(1, round(total_words / 200))
        
        # Readability scores
        try:
            flesch_score = flesch_reading_ease(text)
            grade_level = flesch_kincaid_grade(text)
        except:
            flesch_score = 0
            grade_level = 0
        
        # Average sentence length
        avg_sentence_length = total_words / total_sentences if total_sentences > 0 else 0
        
        return {
            'reading_time_minutes': reading_time,
            'flesch_score': round(flesch_score, 1),
            'grade_level': round(grade_level, 1),
            'avg_sentence_length': round(avg_sentence_length, 1),
            'total_words': total_words,
            'total_sentences': total_sentences,
            'difficulty': self._get_difficulty_level(flesch_score)
        }
    
    def _get_difficulty_level(self, flesch_score: float) -> str:
        """Get readability difficulty level"""
        if flesch_score >= 90:
            return "Very Easy"
        elif flesch_score >= 80:
            return "Easy"
        elif flesch_score >= 70:
            return "Fairly Easy"
        elif flesch_score >= 60:
            return "Standard"
        elif flesch_score >= 50:
            return "Fairly Difficult"
        elif flesch_score >= 30:
            return "Difficult"
        else:
            return "Very Difficult"
    
    def _analyze_seo(self, soup: BeautifulSoup, title: str, paragraphs: List[str]) -> Dict[str, Any]:
        """Analyze SEO elements"""
        # Meta tags
        meta_title = soup.find('meta', property='og:title')
        meta_description = soup.find('meta', attrs={'name': 'description'})
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        
        # Headings structure
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        heading_structure = {}
        for h in headings:
            tag_name = h.name
            heading_structure[tag_name] = heading_structure.get(tag_name, 0) + 1
        
        # Keyword density
        text = ' '.join(paragraphs).lower()
        words = text.split()
        word_count = Counter(words)
        
        # Image analysis
        images = soup.find_all('img')
        images_with_alt = sum(1 for img in images if img.get('alt'))
        
        # Link analysis
        links = soup.find_all('a')
        internal_links = 0
        external_links = 0
        
        return {
            'title': {
                'length': len(title),
                'optimal': 50 <= len(title) <= 60,
                'present': bool(title)
            },
            'meta_description': {
                'text': meta_description.get('content', '') if meta_description else '',
                'length': len(meta_description.get('content', '')) if meta_description else 0,
                'optimal': 150 <= len(meta_description.get('content', '')) <= 160 if meta_description else False,
                'present': meta_description is not None
            },
            'meta_keywords': {
                'present': meta_keywords is not None,
                'text': meta_keywords.get('content', '') if meta_keywords else ''
            },
            'headings': {
                'structure': heading_structure,
                'has_h1': heading_structure.get('h1', 0) > 0,
                'h1_count': heading_structure.get('h1', 0)
            },
            'content': {
                'word_count': len(words),
                'paragraph_count': len(paragraphs),
                'image_count': len(images),
                'images_with_alt': images_with_alt,
                'link_count': len(links)
            },
            'recommendations': self._get_seo_recommendations(title, meta_description, heading_structure, len(words))
        }
    
    def _get_seo_recommendations(self, title: str, meta_description, headings: dict, word_count: int) -> List[str]:
        """Get SEO recommendations"""
        recommendations = []
        
        if not title:
            recommendations.append("Add a page title")
        elif len(title) < 30:
            recommendations.append("Title is too short (aim for 50-60 characters)")
        elif len(title) > 60:
            recommendations.append("Title is too long (aim for 50-60 characters)")
        
        if not meta_description:
            recommendations.append("Add a meta description")
        elif len(meta_description.get('content', '')) < 120:
            recommendations.append("Meta description is too short (aim for 150-160 characters)")
        elif len(meta_description.get('content', '')) > 160:
            recommendations.append("Meta description is too long (aim for 150-160 characters)")
        
        if headings.get('h1', 0) == 0:
            recommendations.append("Add an H1 heading")
        elif headings.get('h1', 0) > 1:
            recommendations.append("Use only one H1 heading per page")
        
        if word_count < 300:
            recommendations.append("Content is too short (aim for at least 300 words)")
        
        return recommendations
    
    def _classify_content(self, title: str, paragraphs: List[str], url: str) -> Dict[str, Any]:
        """Classify content type"""
        text = (title + ' ' + ' '.join(paragraphs)).lower()
        
        scores = {}
        for content_type, keywords in self.classification_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            scores[content_type] = score
        
        # Get the best match
        best_type = max(scores, key=scores.get) if scores else 'unknown'
        confidence = scores[best_type] / len(self.classification_keywords[best_type]) if scores.get(best_type) else 0
        
        # Check URL for additional clues
        url_indicators = {
            'blog': ['/blog/', '/post/', '/article/'],
            'ecommerce': ['/product/', '/shop/', '/buy/', '/cart/'],
            'documentation': ['/docs/', '/api/', '/reference/', '/guide/']
        }
        
        for content_type, patterns in url_indicators.items():
            if any(pattern in url.lower() for pattern in patterns):
                if scores.get(content_type, 0) == 0:
                    scores[content_type] = 1
                else:
                    scores[content_type] += 1
        
        return {
            'type': best_type,
            'confidence': round(confidence, 2),
            'all_scores': scores,
            'language': self._detect_language(text)
        }
    
    def _detect_language(self, text: str) -> str:
        """Simple language detection"""
        # Common English words
        english_words = ['the', 'and', 'is', 'in', 'to', 'of', 'a', 'that', 'it', 'with']
        words = text.lower().split()[:100]  # Check first 100 words
        
        english_count = sum(1 for word in words if word in english_words)
        
        if english_count / len(words) > 0.1:  # If more than 10% are common English words
            return 'en'
        else:
            return 'unknown'
    
    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract page metadata"""
        def _text_from_element(el) -> str:
            if not el:
                return ''
            try:
                return ' '.join([str(s) for s in el.stripped_strings])
            except Exception:
                return ''

        return {
            'url': url,
            'processed_at': datetime.utcnow().isoformat(),
            'word_count': len(' '.join([_text_from_element(p) for p in soup.find_all('p')]).split()),
            'image_count': len(soup.find_all('img')),
            'link_count': len(soup.find_all('a')),
            'form_count': len(soup.find_all('form')),
            'table_count': len(soup.find_all('table')),
            'has_video': bool(soup.find(['video', 'iframe'])),
            'has_audio': bool(soup.find('audio'))
        }
    
    def _create_anchor(self, text: str) -> str:
        """Create URL-friendly anchor from text"""
        # Convert to lowercase and replace spaces/special chars
        anchor = re.sub(r'[^\w\s-]', '', text.lower())
        anchor = re.sub(r'[-\s]+', '-', anchor)
        return anchor.strip('-')
    
    def to_json(self, content: ProcessedContent) -> Dict[str, Any]:
        """Convert processed content to structured JSON"""
        return {
            'title': content.title,
            'headings': content.headings,
            'paragraphs': content.paragraphs,
            'lists': content.lists,
            'keywords': content.keywords,
            'entities': content.entities,
            'summary': content.summary,
            'readability': content.readability,
            'seo': content.seo,
            'classification': content.classification,
            'metadata': content.metadata
        }
