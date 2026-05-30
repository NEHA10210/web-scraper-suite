"""
Data Scraper Module
Scrapes text and image data for AI training datasets.
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import csv
import os
from urllib.parse import urljoin, urlparse
import logging
from datetime import datetime
import time
from PIL import Image
import io
import base64

logger = logging.getLogger(__name__)

class DataScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.data_dir = 'data'
        self.images_dir = os.path.join(self.data_dir, 'images')
        self.ensure_directories()
    
    def is_valid_url(self, url):
        """Validate URL format."""
        try:
            from urllib.parse import urlparse
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def ensure_directories(self):
        """Ensure necessary directories exist."""
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)
    
    def scrape_data(self, url, scrape_type='text'):
        """Main method to scrape data based on type."""
        try:
            # Validate URL
            if not self.is_valid_url(url):
                return {'error': 'Invalid URL format'}
            
            # Fetch webpage
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            if scrape_type == 'text':
                return self.scrape_text_data(url, soup)
            elif scrape_type == 'images':
                return self.scrape_image_data(url, soup)
            elif scrape_type == 'both':
                text_result = self.scrape_text_data(url, soup)
                image_result = self.scrape_image_data(url, soup)
                return {
                    'success': True,
                    'text_data': text_result,
                    'image_data': image_result,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                return {'error': 'Invalid scrape type. Use "text", "images", or "both"'}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {'error': f'Network error: {str(e)}'}
        except Exception as e:
            logger.error(f"Scraping error: {str(e)}")
            return {'error': f'Scraping failed: {str(e)}'}
    
    def scrape_text_data(self, url, soup):
        try:
            # Extract page metadata
            metadata = self.extract_metadata(soup, url)
            
            # Extract main content
            text_content = self.extract_text_content(soup)
            
            # Calculate statistics
            stats = self.calculate_text_stats(text_content)
            
            # Prepare data structure
            text_data = {
                'url': url,
                'title': metadata.get('title', ''),
                'text': text_content,
                'word_count': stats['word_count'],
                'char_count': stats['char_count'],
                'line_count': stats['line_count'],
                'paragraph_count': stats['paragraph_count'],
                'sentence_count': stats['sentence_count'],
                'avg_words_per_sentence': stats['avg_words_per_sentence']
            }
            
            # Save to file
            saved_files = []
            if text_content.strip():
                saved_files = self.save_text_data(text_data)
            
            return {
                'type': 'text',
                'success': True,
                'content': text_data,
                'saved_files': saved_files,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error scraping text data: {str(e)}")
            return {'error': f'Text scraping failed: {str(e)}'}
    
    def scrape_image_data(self, url, soup):
        """Scrape image data from webpage."""
        try:
            # Extract page metadata
            metadata = self.extract_metadata(soup, url)
            
            # Find all images
            images = self.extract_images(soup, url)
            
            # Download images
            downloaded_images = []
            for i, img_info in enumerate(images[:20]):  # Limit to 20 images
                downloaded_img = self.download_image(img_info, i)
                if downloaded_img:
                    downloaded_images.append(downloaded_img)
                time.sleep(0.5)  # Rate limiting
            
            # Prepare data structure
            total_size = sum(img.get('size_bytes', 0) for img in downloaded_images)
            
            image_data = {
                'total_found': len(images),
                'downloaded': len(downloaded_images),
                'total_size_mb': total_size / (1024 * 1024),
                'downloaded_images': downloaded_images
            }
            
            # Save to files
            saved_files = self.save_image_data(image_data, url)
            
            return {
                'type': 'images',
                'success': True,
                'images': image_data,
                'saved_files': saved_files,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error scraping image data: {str(e)}")
            return {'error': f'Image scraping failed: {str(e)}'}
    
    def extract_metadata(self, soup, url):
        """Extract page metadata."""
        return {
            'url': url,
            'title': self.get_title(soup),
            'description': self.get_meta_description(soup),
            'author': self.get_meta_author(soup),
            'publish_date': self.get_publish_date(soup),
            'scraped_at': datetime.now().isoformat()
        }
    
    def extract_text_content(self, soup):
        """Extract clean text content from webpage."""
        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
        
        # Get text content
        text = ' '.join([str(s) for s in soup.stripped_strings])
        
        # Clean up text
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        return text
    
    def calculate_text_stats(self, text):
        """Calculate various text statistics."""
        if not text:
            return {
                'word_count': 0,
                'char_count': 0,
                'line_count': 0,
                'paragraph_count': 0,
                'sentence_count': 0,
                'avg_words_per_sentence': 0
            }
        
        words = text.split()
        sentences = text.split('.') + text.split('!') + text.split('?')
        sentences = [s.strip() for s in sentences if s.strip()]
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        lines = text.split('\n')
        
        avg_words = sum(len(sentence.split()) for sentence in sentences) / len(sentences) if sentences else 0
        
        return {
            'word_count': len(words),
            'char_count': len(text),
            'line_count': len([l for l in lines if l.strip()]),
            'paragraph_count': len(paragraphs),
            'sentence_count': len(sentences),
            'avg_words_per_sentence': round(avg_words, 1)
        }
    
    def extract_images(self, soup, base_url):
        """Extract image information from page."""
        images = []
        
        for img in soup.find_all('img'):
            src = img.get('src')
            if not src:
                continue
            
            # Convert relative URLs to absolute
            from urllib.parse import urljoin
            absolute_url = urljoin(base_url, src)
            
            image_info = {
                'src': absolute_url,
                'alt': img.get('alt', ''),
                'title': img.get('title', ''),
                'width': img.get('width'),
                'height': img.get('height')
            }
            images.append(image_info)
        
        return images
    
    def get_title(self, soup):
        """Get page title."""
        title_tag = soup.find('title')
        if not title_tag:
            return ''
        try:
            return ' '.join([str(s) for s in title_tag.stripped_strings]).strip()
        except Exception:
            return title_tag.string.strip() if getattr(title_tag, 'string', None) else ''
    
    def get_meta_description(self, soup):
        """Get meta description."""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        return meta_desc.get('content') if meta_desc else ''
    
    def get_meta_author(self, soup):
        """Get meta author."""
        meta_author = soup.find('meta', attrs={'name': 'author'})
        return meta_author.get('content') if meta_author else ''
    
    def get_publish_date(self, soup):
        """Get publish date."""
        # Try various meta tags for publish date
        date_selectors = [
            'meta[property="article:published_time"]',
            'meta[name="date"]',
            'meta[name="publish_date"]',
            'meta[property="datePublished"]'
        ]
        
        for selector in date_selectors:
            tag = soup.select_one(selector)
            if tag and tag.get('content'):
                return tag.get('content')
        
        return ''
    
    def save_text_data(self, text_data):
        """Save text data to file."""
        try:
            filename = f"text_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.data_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"URL: {text_data['url']}\n")
                f.write(f"Title: {text_data['title']}\n")
                f.write(f"Scraped: {datetime.now().isoformat()}\n")
                f.write("=" * 50 + "\n\n")
                f.write(text_data['text'])
            
            return [filepath]
        except Exception as e:
            logger.error(f"Error saving text data: {str(e)}")
            return []
    
    def save_image_data(self, image_data, url):
        """Save image data information."""
        try:
            filename = f"image_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(self.data_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    'url': url,
                    'scraped_at': datetime.now().isoformat(),
                    'statistics': image_data
                }, f, indent=2)
            
            return [filepath]
        except Exception as e:
            logger.error(f"Error saving image data: {str(e)}")
            return []
    
    def download_image(self, img_info, index):
        """Download a single image."""
        try:
            response = self.session.get(img_info['src'], timeout=10)
            response.raise_for_status()
            
            # Generate filename
            filename = f"image_{index}_{os.path.basename(img_info['src'].split('?')[0])}"
            if not filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                filename += '.jpg'
            
            filepath = os.path.join(self.images_dir, filename)
            
            # Save image
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            # Convert to base64 for display
            img_data = base64.b64encode(response.content).decode('utf-8')
            data_url = f"data:image/{filename.split('.')[-1]};base64,{img_data}"
            
            return {
                'filename': filename,
                'filepath': filepath,
                'size_bytes': len(response.content),
                'data_url': data_url,
                'original_src': img_info['src']
            }
            
        except Exception as e:
            logger.error(f"Error downloading image {img_info['src']}: {str(e)}")
            return None
