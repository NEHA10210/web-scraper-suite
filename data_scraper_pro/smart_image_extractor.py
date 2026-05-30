"""
Smart Image Extractor Module
Filters out noise images and extracts high-quality content images only.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ImageMetadata:
    """Structured image metadata."""
    url: str
    alt: str
    width: Optional[int]
    height: Optional[int]
    is_lazy: bool
    container_type: str
    filename: str
    dom_position: int = 0
    size_kb: Optional[float] = None
    resolution: int = 0
    is_main_image: bool = False
    content_score: float = 0.0


class SmartImageExtractor:
    """
    Smart image extraction with noise filtering.
    
    Filters out:
    - Icons, logos, sprites
    - Tracking pixels (1x1, etc.)
    - UI elements (buttons, arrows)
    - Small images (< 100px)
    - Images with noise filenames
    """
    
    # Noise patterns to filter out
    NOISE_FILENAMES = [
        'icon', 'logo', 'sprite', 'pixel', 'banner', 'ads', 'advertisement',
        'tracking', 'tracker', 'beacon', 'analytics', 'pixel', 'spacer',
        'blank', 'empty', 'placeholder', 'loading', 'loader', 'spinner',
        'arrow', 'chevron', 'play', 'pause', 'menu', 'hamburger', 'close',
        'x-icon', 'favicon', 'avatar', 'profile', 'user-icon', 'thumb',
        'tiny', 'mini', 'badge', 'pin', 'marker', 'dot', 'bullet',
        'background', 'bg', 'pattern', 'texture', 'gradient', 'header-bg',
        'footer-bg', 'sidebar-bg', 'decoration', 'ornament', 'border'
    ]
    
    # Decorative image patterns
    DECORATIVE_SELECTORS = [
        '.bg-image', '.background', '.hero-bg', '.section-bg',
        '.decoration', '.ornament', '.pattern', '.texture',
        '[class*="bg"]', '[class*="background"]', '[class*="decoration"]'
    ]
    
    # Container types that indicate main content
    CONTENT_CONTAINERS = [
        'article', 'main', 'content', 'product', 'gallery', 'figure',
        'img-container', 'image-container', 'photo', 'media',
        'product-image', 'product-gallery', 'main-image', 'hero'
    ]
    
    # UI container types to deprioritize
    UI_CONTAINERS = [
        'nav', 'navigation', 'header', 'footer', 'sidebar', 'widget',
        'toolbar', 'menu', 'button', 'icon', 'social', 'share'
    ]
    
    def __init__(self, min_width: int = 100, min_height: int = 100):
        """
        Initialize extractor.
        
        Args:
            min_width: Minimum image width to include
            min_height: Minimum image height to include
        """
        self.min_width = min_width
        self.min_height = min_height
        
    def extract_images(self, soup, base_url: str) -> Dict[str, Any]:
        """
        Extract and filter images from HTML with ranking.
        
        Args:
            soup: BeautifulSoup object
            base_url: Base URL for resolving relative URLs
            
        Returns:
            Dictionary with total_found, filtered_count, top_images, and all_images
        """
        all_images = self._extract_all_images(soup, base_url)
        logger.info(f"Found {len(all_images)} total images")
        
        # Filter images
        filtered_images = []
        seen_urls: Set[str] = set()
        
        for img in all_images:
            # Check for duplicates
            if img.url in seen_urls:
                continue
            seen_urls.add(img.url)
            
            # Apply all filters
            if self._is_noise_image(img):
                continue
                
            if self._is_too_small(img):
                continue
                
            if self._has_noise_filename(img):
                continue
            
            # Calculate content score and metadata
            self._calculate_content_score(img, soup)
            self._estimate_image_size(img)
            
            filtered_images.append(img)
        
        logger.info(f"Filtered to {len(filtered_images)} relevant images")
        
        # Rank images
        ranked_images = self._rank_images(filtered_images)
        
        # Separate top images (best 20% or max 10)
        top_count = min(10, max(1, len(ranked_images) // 5))
        top_images = ranked_images[:top_count]
        
        # Convert to output format
        output_images = [self._format_image(img) for img in ranked_images]
        output_top = [self._format_image(img) for img in top_images]
        
        return {
            'total_found': len(all_images),
            'filtered_count': len(filtered_images),
            'top_images': output_top,
            'all_images': output_images
        }
    
    def _extract_all_images(self, soup, base_url: str) -> List[ImageMetadata]:
        """Extract all images with lazy loading support and position tracking."""
        images = []
        seen_urls: Set[str] = set()
        
        for idx, img_element in enumerate(soup.find_all('img')):
            # Get actual URL (handle lazy loading)
            url = self._get_image_url(img_element, base_url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Get dimensions
            width, height = self._get_image_dimensions(img_element)
            
            # Get alt text
            alt = img_element.get('alt', '') or ''
            
            # Check if lazy loaded
            is_lazy = bool(img_element.get('data-src') or img_element.get('data-lazy') or img_element.get('data-original'))
            
            # Detect container type
            container_type = self._detect_container_type(img_element)
            
            # Extract filename
            filename = self._extract_filename(url)
            
            # Calculate resolution
            resolution = (width or 0) * (height or 0)
            
            # Create metadata object
            img_metadata = ImageMetadata(
                url=url,
                alt=alt,
                width=width,
                height=height,
                is_lazy=is_lazy,
                container_type=container_type,
                filename=filename,
                dom_position=idx,
                resolution=resolution
            )
            
            # Skip decorative images
            if self._is_decorative_image(img_metadata, img_element):
                logger.debug(f"Skipping decorative image: {url}")
                continue
            
            images.append(img_metadata)
        
        return images
    
    def _get_image_url(self, img, base_url: str) -> Optional[str]:
        """Extract actual image URL with lazy loading support."""
        # Priority order for image sources
        src_attrs = [
            'data-src',      # Common lazy loading
            'data-lazy',     # Lazy load plugin
            'data-original', # Original image
            'data-srcset',   # Handle srcset
            'src'            # Standard src
        ]
        
        for attr in src_attrs:
            value = img.get(attr)
            if value:
                # Handle srcset - take first URL
                if attr == 'data-srcset' or (attr == 'srcset' and not img.get('src')):
                    urls = self._parse_srcset(value)
                    if urls:
                        return urljoin(base_url, urls[0])
                else:
                    return urljoin(base_url, value)
        
        # Check for srcset as fallback
        srcset = img.get('srcset')
        if srcset:
            urls = self._parse_srcset(srcset)
            if urls:
                return urljoin(base_url, urls[0])
        
        return None
    
    def _parse_srcset(self, srcset: str) -> List[str]:
        """Parse srcset attribute to extract URLs."""
        if not srcset:
            return []
        
        urls = []
        # Split by comma and extract URLs
        parts = srcset.split(',')
        for part in parts:
            # Remove size descriptors (e.g., " 2x", " 300w")
            url = part.strip().split()[0]
            if url:
                urls.append(url)
        
        return urls
    
    def _get_image_dimensions(self, img) -> Tuple[Optional[int], Optional[int]]:
        """Extract image dimensions from attributes."""
        width = img.get('width')
        height = img.get('height')
        
        # Convert to int if present
        try:
            width = int(width) if width else None
        except (ValueError, TypeError):
            width = None
            
        try:
            height = int(height) if height else None
        except (ValueError, TypeError):
            height = None
        
        return width, height
    
    def _detect_container_type(self, img) -> str:
        """Detect the type of container the image is in."""
        # Check parent elements up to 5 levels
        parent = img.parent
        depth = 0
        
        while parent and depth < 5:
            # Get classes and id
            classes = parent.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            
            parent_id = parent.get('id', '').lower()
            parent_classes = [c.lower() for c in classes]
            
            # Check for content containers
            combined = ' '.join(parent_classes + [parent_id])
            
            for container in self.CONTENT_CONTAINERS:
                if container in combined:
                    return 'content'
            
            for ui in self.UI_CONTAINERS:
                if ui in combined:
                    return 'ui'
            
            # Check tag name
            if parent.name in ['article', 'main', 'figure']:
                return 'content'
            if parent.name in ['nav', 'header', 'footer', 'aside']:
                return 'ui'
            
            parent = parent.parent
            depth += 1
        
        return 'unknown'
    
    def _extract_filename(self, url: str) -> str:
        """Extract filename from URL."""
        try:
            parsed = urlparse(url)
            path = parsed.path
            filename = path.split('/')[-1].lower()
            # Remove query parameters
            filename = filename.split('?')[0]
            return filename
        except Exception:
            return ''
    
    def _is_noise_image(self, img: ImageMetadata) -> bool:
        """Check if image is noise (UI element, tracking pixel, etc.)."""
        # Check dimensions for tracking pixels
        if img.width == 1 and img.height == 1:
            return True
        
        if img.width == 0 or img.height == 0:
            return True
        
        # Check filename patterns
        if self._has_noise_filename(img):
            return True
        
        # UI container
        if img.container_type == 'ui':
            return True
        
        return False
    
    def _is_decorative_image(self, img, img_element) -> bool:
        """Check if image is decorative/background."""
        # Check CSS selectors for decorative patterns
        for selector in self.DECORATIVE_SELECTORS:
            try:
                if img_element.select_one(selector) or img_element.matches(selector):
                    return True
            except:
                pass
        
        # Check parent elements for decorative classes
        parent = img_element.parent
        depth = 0
        while parent and depth < 3:
            classes = parent.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            
            class_str = ' '.join(classes).lower()
            if any(pattern in class_str for pattern in ['bg', 'background', 'decoration', 'pattern', 'texture']):
                return True
            
            parent = parent.parent
            depth += 1
        
        return False
    
    def _is_too_small(self, img: ImageMetadata) -> bool:
        """Check if image is too small to be meaningful."""
        if img.width is not None and img.width < self.min_width:
            return True
        
        if img.height is not None and img.height < self.min_height:
            return True
        
        return False
    
    def _has_noise_filename(self, img: ImageMetadata) -> bool:
        """Check if filename contains noise indicators."""
        filename = img.filename
        
        for pattern in self.NOISE_FILENAMES:
            if pattern in filename:
                logger.debug(f"Filtered by filename: {filename} (matched: {pattern})")
                return True
        
        return False
    
    def _format_image(self, img: ImageMetadata) -> Dict[str, Any]:
        """Format image metadata for output."""
        return {
            'url': img.url,
            'alt': img.alt,
            'width': img.width,
            'height': img.height,
            'size_kb': img.size_kb,
            'is_lazy': img.is_lazy,
            'container_type': img.container_type,
            'resolution': img.resolution,
            'is_main_image': img.is_main_image,
            'content_score': round(img.content_score, 2)
        }
    
    def _calculate_content_score(self, img: ImageMetadata, soup) -> None:
        """Calculate content relevance score for an image."""
        score = 0.0
        
        # Resolution score (0-30 points)
        if img.resolution > 0:
            if img.resolution >= 1000000:  # >= 1MP
                score += 30
            elif img.resolution >= 500000:  # >= 0.5MP
                score += 20
            elif img.resolution >= 100000:  # >= 0.1MP
                score += 10
        
        # Container type score (0-25 points)
        if img.container_type == 'content':
            score += 25
        elif img.container_type == 'unknown':
            score += 10
        
        # Position score (0-20 points) - earlier in DOM is better
        total_images = len(soup.find_all('img'))
        if total_images > 0:
            position_ratio = 1 - (img.dom_position / total_images)
            score += position_ratio * 20
        
        # Alt text presence (0-10 points)
        if img.alt and len(img.alt.strip()) > 10:
            score += 10
        elif img.alt:
            score += 5
        
        # Size dimensions (0-15 points)
        if img.width and img.height:
            if img.width >= 800 and img.height >= 600:
                score += 15
            elif img.width >= 400 and img.height >= 300:
                score += 10
            elif img.width >= 200 and img.height >= 150:
                score += 5
        
        img.content_score = score
        
        # Mark as main image if score is high enough
        img.is_main_image = score >= 70
    
    def _estimate_image_size(self, img: ImageMetadata) -> None:
        """Estimate image file size based on dimensions and format."""
        if not img.width or not img.height:
            img.size_kb = None
            return
        
        # Base estimation by resolution
        pixels = img.width * img.height
        
        # Estimate based on typical compression ratios
        # JPEG: ~1-2 KB per 1000px for good quality
        # PNG: ~2-4 KB per 1000px for images with text/logos
        # WebP: ~0.8-1.5 KB per 1000px
        
        # Determine likely format from extension
        ext = img.filename.lower().split('.')[-1] if '.' in img.filename else ''
        
        if ext in ['jpg', 'jpeg']:
            kb_per_1k = 1.5
        elif ext == 'png':
            kb_per_1k = 3.0
        elif ext == 'webp':
            kb_per_1k = 1.0
        elif ext == 'gif':
            kb_per_1k = 2.0
        else:
            kb_per_1k = 1.5  # Default assumption
        
        # Calculate estimated size
        estimated_kb = (pixels / 1000) * kb_per_1k
        
        # Adjust for content type
        if img.container_type == 'content':
            # Content images are usually higher quality
            estimated_kb *= 1.2
        
        img.size_kb = round(estimated_kb, 1)
    
    def _rank_images(self, images: List[ImageMetadata]) -> List[ImageMetadata]:
        """Rank images by content score and other factors."""
        # Sort by content score (descending), then resolution (descending)
        return sorted(
            images,
            key=lambda x: (x.content_score, x.resolution, -x.dom_position),
            reverse=True
        )
