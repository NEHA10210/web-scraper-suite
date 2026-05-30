"""
Page Type Detection Module
Analyzes web pages to determine if they are articles, homepages, or listing pages.
"""

from dataclasses import dataclass
from typing import Dict, Any
from bs4 import BeautifulSoup
import re

@dataclass
class PageFeatures:
    """Features extracted from a page for classification."""
    paragraph_count: int = 0
    link_count: int = 0
    text_length: int = 0
    has_article_tag: bool = False
    has_main_tag: bool = False
    heading_count: int = 0
    list_count: int = 0
    image_count: int = 0
    unique_links: int = 0

class PageClassifier:
    """Detects page types using heuristics and content analysis."""
    
    def __init__(self):
        self.article_keywords = {
            'article', 'post', 'story', 'news', 'blog', 'tutorial',
            'guide', 'review', 'analysis', 'report', 'opinion'
        }
        self.listing_keywords = {
            'list', 'index', 'directory', 'archive', 'category',
            'search', 'browse', 'collection', 'gallery'
        }
    
    def classify_page(self, soup: BeautifulSoup, url: str = "") -> Dict[str, Any]:
        """
        Classify the page type and extract features.
        
        Returns:
            Dict with page_type, features, and confidence
        """
        features = self._extract_features(soup)
        page_type = self._determine_page_type(features, url)
        confidence = self._calculate_confidence(features, page_type)
        
        return {
            "page_type": page_type,
            "features": features.__dict__,
            "confidence": confidence,
            "recommendations": self._get_recommendations(page_type, features)
        }
    
    def _extract_features(self, soup: BeautifulSoup) -> PageFeatures:
        """Extract structural features from the page."""
        # Count paragraphs
        paragraphs = soup.find_all('p')
        paragraph_count = len(paragraphs)
        
        # Count links
        links = soup.find_all('a', href=True)
        link_count = len(links)
        
        # Count unique links
        unique_hrefs = set(link.get('href', '') for link in links)
        unique_links = len(unique_hrefs)
        
        # Calculate text length (sum of paragraph text)
        text_length = sum(len(p.get_text(strip=True)) for p in paragraphs)
        
        # Check for semantic tags
        has_article_tag = bool(soup.find('article'))
        has_main_tag = bool(soup.find('main'))
        
        # Count headings
        heading_count = len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
        
        # Count lists
        list_count = len(soup.find_all(['ul', 'ol', 'dl']))
        
        # Count images
        image_count = len(soup.find_all('img'))
        
        return PageFeatures(
            paragraph_count=paragraph_count,
            link_count=link_count,
            text_length=text_length,
            has_article_tag=has_article_tag,
            has_main_tag=has_main_tag,
            heading_count=heading_count,
            list_count=list_count,
            image_count=image_count,
            unique_links=unique_links
        )
    
    def _determine_page_type(self, features: PageFeatures, url: str) -> str:
        """Determine page type based on features and URL patterns."""
        # URL-based hints
        url_lower = url.lower()
        url_score = {
            'article': 0,
            'homepage': 0,
            'listing': 0
        }
        
        # Check URL patterns
        if any(keyword in url_lower for keyword in self.article_keywords):
            url_score['article'] += 2
        if any(keyword in url_lower for keyword in self.listing_keywords):
            url_score['listing'] += 2
        if url.endswith('/') or url.endswith('/index.html') or 'home' in url_lower:
            url_score['homepage'] += 1
        
        # Feature-based scoring
        feature_score = {
            'article': 0,
            'homepage': 0,
            'listing': 0
        }
        
        # Article indicators
        if features.has_article_tag:
            feature_score['article'] += 3
        if features.paragraph_count > 5:
            feature_score['article'] += 2
        if features.text_length > 1000:
            feature_score['article'] += 2
        if features.heading_count >= 3:
            feature_score['article'] += 1
        
        # Homepage indicators
        if features.link_count > 50:
            feature_score['homepage'] += 2
        if features.unique_links > 30:
            feature_score['homepage'] += 1
        if features.paragraph_count < 5 and features.link_count > 20:
            feature_score['homepage'] += 2
        
        # Listing indicators
        if features.list_count > 3:
            feature_score['listing'] += 2
        if features.link_count > 20 and features.paragraph_count < 10:
            feature_score['listing'] += 1
        if features.image_count > 10:
            feature_score['listing'] += 1
        
        # Combine scores
        total_score = {
            'article': url_score['article'] + feature_score['article'],
            'homepage': url_score['homepage'] + feature_score['homepage'],
            'listing': url_score['listing'] + feature_score['listing']
        }
        
        # Return the type with highest score
        return max(total_score, key=total_score.get)
    
    def _calculate_confidence(self, features: PageFeatures, page_type: str) -> float:
        """Calculate confidence score for the classification."""
        base_confidence = 0.5
        
        # Increase confidence based on clear indicators
        if page_type == 'article':
            if features.has_article_tag:
                base_confidence += 0.3
            if features.paragraph_count > 10:
                base_confidence += 0.2
        elif page_type == 'homepage':
            if features.link_count > 100:
                base_confidence += 0.3
            if features.unique_links > 50:
                base_confidence += 0.2
        elif page_type == 'listing':
            if features.list_count > 5:
                base_confidence += 0.3
            if features.link_count > 30:
                base_confidence += 0.2
        
        return min(base_confidence, 1.0)
    
    def _get_recommendations(self, page_type: str, features: PageFeatures) -> list:
        """Get recommendations based on page type and features."""
        recommendations = []
        
        if page_type == 'article':
            recommendations.append("Extract main article content")
            if features.text_length < 500:
                recommendations.append("Consider dynamic scraping for better content")
        elif page_type == 'homepage':
            recommendations.append("Extract top article links")
            recommendations.append("Crawl and scrape linked articles")
            if features.link_count > 100:
                recommendations.append("Limit crawling to top 10 links for performance")
        elif page_type == 'listing':
            recommendations.append("Extract listing items")
            recommendations.append("Scrape top items from the list")
        
        if features.paragraph_count < 3:
            recommendations.append("Low content detected - try dynamic scraping")
        
        return recommendations
