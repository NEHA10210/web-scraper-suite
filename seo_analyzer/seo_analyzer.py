"""
SEO Analyzer Module
Analyzes web pages for SEO factors including meta tags, headings, links, and content.
"""

import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import logging
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

class SEOAnalyzer:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def is_valid_url(self, url):
        """Validate URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def check_heading_hierarchy(self, soup):
        """Check if headings follow proper hierarchy."""
        if not soup:
            return True
            
        headings = []
        for i in range(1, 7):
            for heading in soup.find_all(f'h{i}'):
                headings.append(int(heading.name[1]))
        
        if not headings:
            return True
        
        # Check if headings are in proper order (no skipping levels)
        for i in range(1, len(headings)):
            if headings[i] - headings[i-1] > 1:
                return False
        return True
    
    def check_open_graph_tags(self, soup):
        """Check for Open Graph meta tags."""
        if not soup:
            return False
            
        og_tags = ['og:title', 'og:description', 'og:image', 'og:url']
        found_tags = []
        
        for tag in og_tags:
            meta_tag = soup.find('meta', attrs={'property': tag})
            if meta_tag and meta_tag.get('content'):
                found_tags.append(tag)
        
        return len(found_tags) >= 2  # At least 2 OG tags present
    
    def check_twitter_card_tags(self, soup):
        """Check for Twitter Card meta tags."""
        if not soup:
            return False
            
        twitter_tags = ['twitter:card', 'twitter:title', 'twitter:description', 'twitter:image']
        found_tags = []
        
        for tag in twitter_tags:
            meta_tag = soup.find('meta', attrs={'name': tag})
            if meta_tag and meta_tag.get('content'):
                found_tags.append(tag)
        
        return len(found_tags) >= 2  # At least 2 Twitter tags present
    
    def check_mobile_friendly(self, soup):
        """Check if page has mobile-friendly indicators."""
        if not soup:
            return False
            
        # Check for viewport meta tag
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        if not viewport:
            return False
        
        # Check for responsive design indicators
        responsive_indicators = [
            soup.find('meta', attrs={'name': 'viewport'}),
            soup.find('meta', attrs={'name': 'mobile-web-app-capable'}),
            soup.find('meta', attrs={'name': 'apple-mobile-web-app-capable'})
        ]
        
        return any(indicator for indicator in responsive_indicators)
    
    def analyze_seo(self, url):
        """Perform comprehensive SEO analysis of a webpage."""
        try:
            # Validate URL
            if not self.is_valid_url(url):
                return {'error': 'Invalid URL format'}
            
            # Fetch webpage
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract SEO data
            seo_data = {
                'url': url,
                'timestamp': datetime.now().isoformat(),
                'basic_info': self.get_basic_info(soup),
                'meta_tags': self.analyze_meta_tags(soup),
                'headings': self.analyze_headings(soup),
                'links': self.analyze_links(soup, url),
                'images': self.analyze_images(soup, url),
                'content': self.analyze_content(soup),
                'technical': self.analyze_technical(soup, response),
                'performance': self.analyze_performance(response)
            }
            
            # Calculate SEO score
            seo_data['seo_score'] = self.calculate_seo_score(seo_data)
            
            # Generate recommendations
            seo_data['recommendations'] = self.generate_recommendations(seo_data)
            
            return seo_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {'error': f'Network error: {str(e)}'}
        except Exception as e:
            logger.error(f"SEO analysis error: {str(e)}")
            return {'error': f'Analysis failed: {str(e)}'}
    
    def get_basic_info(self, soup):
        """Extract basic page information."""
        return {
            'title': self.get_page_title(soup),
            'title_length': len(self.get_page_title(soup) or ''),
            'description': self.get_meta_description(soup),
            'description_length': len(self.get_meta_description(soup) or ''),
            'keywords': self.get_meta_keywords(soup),
            'language': self.get_language(soup),
            'canonical_url': self.get_canonical_url(soup)
        }
    
    def analyze_meta_tags(self, soup):
        """Analyze meta tags."""
        # Extract specific meta tags that frontend expects
        title = self.get_page_title(soup)
        description = self.get_meta_description(soup)
        keywords = self.get_meta_keywords(soup)
        
        # Find all meta tags
        all_meta_tags = []
        for meta in soup.find_all('meta'):
            tag_info = {
                'name': meta.get('name') or meta.get('property') or meta.get('http-equiv'),
                'content': meta.get('content'),
                'charset': meta.get('charset')
            }
            all_meta_tags.append(tag_info)
        
        # Check for essential meta tags
        essential_tags = ['description', 'keywords', 'viewport', 'robots']
        missing_tags = []
        
        for tag in essential_tags:
            found = False
            for meta in all_meta_tags:
                if meta['name'] == tag:
                    found = True
                    break
            if not found:
                missing_tags.append(tag)
        
        return {
            'title': title,
            'description': description,
            'keywords': keywords,
            'all_tags': all_meta_tags,
            'missing_essential': missing_tags,
            'has_description': bool(description),
            'has_viewport': any(meta['name'] == 'viewport' for meta in all_meta_tags),
            'has_robots': any(meta['name'] == 'robots' for meta in all_meta_tags)
        }
    
    def analyze_headings(self, soup):
        """Analyze heading structure."""
        headings = {"h1": [], "h2": [], "h3": [], "h4": [], "h5": [], "h6": []}
        
        for level in headings:
            for heading in soup.find_all(level):
                heading_text = self._extract_text(heading)
                headings[level].append({
                    'text': heading_text,
                    'length': len(heading_text)
                })
        
        # Check heading hierarchy
        h1_count = len(headings["h1"])
        has_h1 = h1_count > 0
        proper_hierarchy = self.check_heading_hierarchy(soup)
        
        return headings  # Return just the headings object as frontend expects
    
    def analyze_links(self, soup, base_url):
        """Analyze internal and external links."""
        internal_links = []
        external_links = []
        broken_links = []
        
        base_domain = urlparse(base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = self._extract_text(link)
            
            # Skip empty and anchor links
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)
            
            link_info = {
                'url': absolute_url,
                'text': text,
                'is_external': urlparse(absolute_url).netloc != base_domain
            }
            
            # Check link status (limit to first 10 links to avoid timeout)
            if len(internal_links) + len(external_links) < 10:
                try:
                    response = self.session.head(absolute_url, timeout=5, allow_redirects=True)
                    link_info['status_code'] = response.status_code
                    link_info['is_broken'] = response.status_code != 200
                except:
                    link_info['status_code'] = 0
                    link_info['is_broken'] = True
            else:
                link_info['status_code'] = None
                link_info['is_broken'] = False
            
            if link_info['is_external']:
                external_links.append(link_info)
            else:
                internal_links.append(link_info)
            
            if link_info.get('is_broken', False):
                broken_links.append(link_info)
        
        return {
            'internal_count': len(internal_links),
            'external_count': len(external_links),
            'total_count': len(internal_links) + len(external_links),
            'broken_count': len(broken_links),
            'broken_links': broken_links[:5],  # Show first 5 broken links
            'internal_links': internal_links[:50],  # Limit to first 50
            'external_links': external_links[:50]  # Limit to first 50
        }
    
    def analyze_images(self, soup, base_url):
        """Analyze images for SEO."""
        images = []
        images_without_alt = 0
        
        for img in soup.find_all('img'):
            # Handle lazy-loaded images with multiple src attributes
            src = (img.get('src') or 
                   img.get('data-src') or 
                   img.get('data-lazy') or 
                   img.get('srcset', '').split()[0] if img.get('srcset') else None)
            
            if not src:
                continue
            
            absolute_src = urljoin(base_url, src)
            alt_text = img.get('alt', '')
            
            image_info = {
                'src': absolute_src,
                'alt': alt_text,
                'has_alt': bool(alt_text.strip()),
                'alt_length': len(alt_text.strip())
            }
            
            images.append(image_info)
            if not alt_text.strip():
                images_without_alt += 1
        
        return {
            'total_count': len(images),
            'with_alt_count': len(images) - images_without_alt,
            'without_alt_count': images_without_alt,
            'alt_coverage': ((len(images) - images_without_alt) / len(images) * 100) if images else 0,
            'images': images[:20]  # Limit to first 20 for detailed view
        }
    
    def analyze_content(self, soup):
        """Analyze content quality."""
        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
        
        # Get text content
        text = self._extract_text(soup)
        words = text.split()
        word_count = len(words)
        
        # Common stopwords to filter out
        stopwords = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'among', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
            'we', 'they', 'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those',
            'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must',
            'can', 'shall', 'a', 'an', 'as', 'if', 'when', 'where', 'why', 'how', 'all', 'any',
            'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
            'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'now', 'also', 'here',
            'there', 'then', 'again', 'further', 'once', 'here', 'there', 'why', 'how'
        }
        
        # Calculate keyword density (filtering stopwords and short words)
        meaningful_words = [word.lower().strip('.,!?;:"()[]{}') for word in words 
                           if len(word.strip('.,!?;:"()[]{}')) > 3 
                           and word.lower().strip('.,!?;:"()[]{}') not in stopwords]
        
        word_freq = Counter(meaningful_words)
        total_words = len(meaningful_words)
        
        # Get top keywords
        top_keywords = []
        for word, freq in word_freq.most_common(10):
            density = (freq / total_words * 100) if total_words > 0 else 0
            top_keywords.append({
                'keyword': word,
                'frequency': freq,
                'density': round(density, 2)
            })
        
        # Check for readability
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        sentence_count = len(sentences)
        avg_words_per_sentence = word_count / sentence_count if sentence_count > 0 else 0
        
        return {
            'word_count': word_count,
            'sentence_count': sentence_count,
            'avg_words_per_sentence': round(avg_words_per_sentence, 1),
            'top_keywords': top_keywords[:5],  # Return top 5 keywords
            'has_enough_content': word_count >= 300,
            'readability_score': min(100, max(0, 100 - (avg_words_per_sentence - 15) * 2))
        }
    
    def analyze_technical(self, soup, response):
        """Analyze technical SEO factors."""
        return {
            'status_code': response.status_code,
            'response_time': response.elapsed.total_seconds(),
            'content_type': response.headers.get('content-type', ''),
            'content_length': len(response.content),
            'has_schema': bool(soup.find_all(attrs={'type': 'application/ld+json'})),
            'has_open_graph': self.check_open_graph_tags(soup),
            'has_twitter_cards': self.check_twitter_card_tags(soup),
            'uses_https': response.url.startswith('https://'),
            'is_mobile_friendly': self.check_mobile_friendly(soup)
        }
    
    def analyze_performance(self, response):
        """Analyze basic performance metrics."""
        load_time = response.elapsed.total_seconds()
        page_size_kb = len(response.content) / 1024
        
        # Performance grading
        if load_time < 1:
            load_grade = 'A'
        elif load_time < 3:
            load_grade = 'B'
        else:
            load_grade = 'C'
        
        return {
            'load_time': load_time,
            'load_grade': load_grade,
            'size_kb': page_size_kb,
            'size_mb': page_size_kb / 1024,
            'is_fast': load_time < 2.0,
            'size_optimized': len(response.content) < 1024 * 1024  # Less than 1MB
        }
    
    def calculate_seo_score(self, seo_data):
        """Calculate overall SEO score based on various factors."""
        score = 0
        max_score = 100
        
        # Individual component scores
        scores = {
            'technical': 0,
            'content': 0,
            'performance': 0
        }
        
        # Technical SEO (40 points)
        basic_info = seo_data.get('basic_info', {})
        meta_tags = seo_data.get('meta_tags', {})
        
        # Title (15 points)
        if basic_info.get('title'):
            title_length = len(basic_info.get('title', ''))
            if 30 <= title_length <= 60:
                score += 15
                scores['technical'] += 15
            elif title_length > 0:
                score += 10
                scores['technical'] += 10
        
        # Meta description (10 points)
        if basic_info.get('description'):
            desc_length = len(basic_info.get('description', ''))
            if 120 <= desc_length <= 160:
                score += 10
                scores['technical'] += 10
            elif desc_length > 0:
                score += 5
                scores['technical'] += 5
        
        # Meta keywords (5 points - optional)
        if meta_tags.get('keywords'):
            score += 5
            scores['technical'] += 5
        
        # Headings structure (10 points)
        headings = seo_data.get('headings', {})
        if headings.get('h1') and len(headings['h1']) == 1:
            score += 5
            scores['technical'] += 5
        if headings.get('h2') and len(headings['h2']) > 0:
            score += 5
            scores['technical'] += 5
        
        # Content SEO (30 points)
        content = seo_data.get('content', {})
        word_count = content.get('word_count', 0)
        
        # Word count (15 points)
        if word_count >= 300:
            score += 15
            scores['content'] += 15
        elif word_count >= 100:
            score += 10
            scores['content'] += 10
        elif word_count > 0:
            score += 5
            scores['content'] += 5
        
        # Image optimization (15 points)
        images = seo_data.get('images', {})
        if images.get('total_count', 0) > 0:
            alt_coverage = images.get('alt_coverage', 0)
            if alt_coverage >= 80:
                score += 15
                scores['content'] += 15
            elif alt_coverage >= 50:
                score += 10
                scores['content'] += 10
            elif alt_coverage > 0:
                score += 5
                scores['content'] += 5
        
        # Performance (30 points)
        technical = seo_data.get('technical', {})
        performance = seo_data.get('performance', {})
        
        # Page load time (15 points)
        load_time = performance.get('load_time', 0)
        if load_time > 0:
            if load_time < 1:
                score += 15
                scores['performance'] += 15
            elif load_time < 3:
                score += 10
                scores['performance'] += 10
            elif load_time < 5:
                score += 5
                scores['performance'] += 5
        
        # Page size (10 points)
        page_size = technical.get('page_size', 0)
        if page_size > 0:
            page_size_mb = page_size / (1024 * 1024)
            if page_size_mb < 1:
                score += 10
                scores['performance'] += 10
            elif page_size_mb < 2:
                score += 5
                scores['performance'] += 5
        
        # Status code (5 points)
        if technical.get('status_code') == 200:
            score += 5
            scores['performance'] += 5
        
        # Scale scores to 100
        final_score = min(score, max_score)
        
        return {
            'overall_score': final_score,
            'technical_score': min(scores['technical'], 40),
            'content_score': min(scores['content'], 30),
            'performance_score': min(scores['performance'], 30)
        }
    
    def generate_recommendations(self, seo_data):
        """Generate SEO recommendations based on analysis."""
        recommendations = []
        
        # Title recommendations
        basic_info = seo_data.get('basic_info', {})
        if not basic_info.get('title'):
            recommendations.append({
                'type': 'critical',
                'category': 'title',
                'message': 'Add a page title for better SEO'
            })
        else:
            title_length = len(basic_info.get('title', ''))
            if title_length < 30:
                recommendations.append({
                    'type': 'warning',
                    'category': 'title',
                    'message': f'Title is too short ({title_length} chars). Aim for 30-60 characters.'
                })
            elif title_length > 60:
                recommendations.append({
                    'type': 'warning',
                    'category': 'title',
                    'message': f'Title is too long ({title_length} chars). Aim for 30-60 characters.'
                })
        
        # Meta description recommendations
        if not basic_info.get('description'):
            recommendations.append({
                'type': 'critical',
                'category': 'meta',
                'message': 'Add a meta description to improve search engine snippets'
            })
        else:
            desc_length = len(basic_info.get('description', ''))
            if desc_length < 120:
                recommendations.append({
                    'type': 'warning',
                    'category': 'meta',
                    'message': f'Meta description is too short ({desc_length} chars). Aim for 120-160 characters.'
                })
            elif desc_length > 160:
                recommendations.append({
                    'type': 'warning',
                    'category': 'meta',
                    'message': f'Meta description is too long ({desc_length} chars). Aim for 120-160 characters.'
                })
        
        # Heading recommendations
        headings = seo_data.get('headings', {})
        h1_count = len(headings.get('h1', []))
        if h1_count == 0:
            recommendations.append({
                'type': 'critical',
                'category': 'headings',
                'message': 'Add an H1 tag to improve page structure and SEO'
            })
        elif h1_count > 1:
            recommendations.append({
                'type': 'warning',
                'category': 'headings',
                'message': 'Use only one H1 tag per page for better SEO'
            })
        
        h2_count = len(headings.get('h2', []))
        if h2_count == 0:
            recommendations.append({
                'type': 'warning',
                'category': 'headings',
                'message': 'Add H2 tags to structure your content better'
            })
        
        # Image recommendations
        images = seo_data.get('images', {})
        if images.get('without_alt_count', 0) > 0:
            recommendations.append({
                'type': 'warning',
                'category': 'images',
                'message': f'Add alt text to {images.get("without_alt_count")} images for better accessibility and SEO'
            })
        
        # Content recommendations
        content = seo_data.get('content', {})
        word_count = content.get('word_count', 0)
        if word_count < 300:
            recommendations.append({
                'type': 'warning',
                'category': 'content',
                'message': f'Content is too short ({word_count} words). Aim for at least 300 words for better SEO.'
            })
        
        # Link recommendations
        links = seo_data.get('links', {})
        if links.get('internal_count', 0) == 0:
            recommendations.append({
                'type': 'warning',
                'category': 'links',
                'message': 'Add internal links to improve site navigation and SEO'
            })
        
        if links.get('external_count', 0) == 0:
            recommendations.append({
                'type': 'info',
                'category': 'links',
                'message': 'Consider adding external links to authoritative sources'
            })
        
        # Performance recommendations
        performance = seo_data.get('performance', {})
        load_time = performance.get('load_time', 0)
        if load_time > 3:
            recommendations.append({
                'type': 'warning',
                'category': 'performance',
                'message': f'Page load time is slow ({load_time}s). Optimize images and code for better performance.'
            })
        elif load_time > 1:
            recommendations.append({
                'type': 'info',
                'category': 'performance',
                'message': f'Page load time could be improved ({load_time}s). Aim for under 1 second.'
            })
        
        # Broken links recommendations
        links = seo_data.get('links', {})
        broken_count = links.get('broken_count', 0)
        if broken_count > 0:
            recommendations.append({
                'type': 'critical',
                'category': 'links',
                'message': f'Found {broken_count} broken links. Fix them for better user experience and SEO.'
            })
        
        # Content quality recommendations
        content = seo_data.get('content', {})
        readability_score = content.get('readability_score', 0)
        if readability_score < 60:
            recommendations.append({
                'type': 'warning',
                'category': 'content',
                'message': f'Content readability is low ({readability_score}/100). Use shorter sentences and simpler language.'
            })
        
        # Technical SEO recommendations
        technical = seo_data.get('technical', {})
        if not technical.get('uses_https', False):
            recommendations.append({
                'type': 'critical',
                'category': 'technical',
                'message': 'Switch to HTTPS for better security and SEO ranking.'
            })
        
        if not technical.get('is_mobile_friendly', False):
            recommendations.append({
                'type': 'warning',
                'category': 'technical',
                'message': 'Add viewport meta tag for better mobile experience.'
            })
        
        return recommendations
    
    def get_page_title(self, soup):
        """Get page title."""
        title_tag = soup.find('title')
        return self._extract_text(title_tag) if title_tag else None

    def _extract_text(self, element) -> str:
        """Extract text from BeautifulSoup element without using get_text()."""
        if not element:
            return ''
        try:
            return ' '.join([str(s) for s in element.stripped_strings]).strip()
        except Exception:
            # Fallback
            if hasattr(element, 'string') and element.string:
                return str(element.string).strip()
            return ''
    
    def get_meta_description(self, soup):
        """Get meta description."""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        return meta_desc.get('content') if meta_desc else None
    
    def get_meta_keywords(self, soup):
        """Get meta keywords."""
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        return meta_keywords.get('content') if meta_keywords else None
    
    def get_language(self, soup):
        """Get page language."""
        html_tag = soup.find('html')
        return html_tag.get('lang') if html_tag else None
    
    def get_canonical_url(self, soup):
        """Get canonical URL."""
        canonical = soup.find('link', attrs={'rel': 'canonical'})
        return canonical.get('href') if canonical else None
