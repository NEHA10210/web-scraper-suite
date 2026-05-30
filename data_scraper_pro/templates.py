"""
Scraping templates for different website types
"""

from typing import Dict, Any, List
from dataclasses import dataclass
import json
import logging

logger = logging.getLogger(__name__)

@dataclass
class ScrapingTemplate:
    name: str
    description: str
    category: str
    selectors: Dict[str, str]
    wait_for: str
    scroll: bool = False
    pagination: Optional[Dict[str, str]] = None
    custom_config: Dict[str, Any] = None

class TemplateManager:
    def __init__(self):
        self.templates = self._load_default_templates()
    
    def _load_default_templates(self) -> Dict[str, ScrapingTemplate]:
        """Load default scraping templates"""
        templates = {}
        
        # Blog Template
        templates['blog'] = ScrapingTemplate(
            name='Blog/News Article',
            description='Extract blog posts and news articles',
            category='content',
            selectors={
                'title': 'h1, .entry-title, .post-title, .article-title',
                'author': '.author, .byline, .post-author, [rel="author"]',
                'publish_date': '.date, .published, .post-date, time[datetime]',
                'content': '.entry-content, .post-content, .article-content, .content',
                'excerpt': '.excerpt, .summary, .post-excerpt',
                'categories': '.categories, .tags, .post-categories, .post-tags',
                'comments': '.comments, .comment-list'
            },
            wait_for='.entry-content, .post-content, .article-content',
            scroll=True
        )
        
        # E-commerce Template
        templates['ecommerce'] = ScrapingTemplate(
            name='E-commerce Product',
            description='Extract product information from online stores',
            category='ecommerce',
            selectors={
                'product_title': '.product-title, h1, .product-name',
                'price': '.price, .product-price, [data-price]',
                'description': '.product-description, .description, .product-details',
                'images': '.product-image img, .gallery img, .product-photo img',
                'specifications': '.specifications, .product-specs, .product-details table',
                'availability': '.stock, .availability, .in-stock',
                'rating': '.rating, .stars, .review-rating',
                'reviews': '.reviews, .customer-reviews, .testimonials',
                'sku': '.sku, .product-sku, [data-sku]'
            },
            wait_for='.product-title, h1',
            scroll=True,
            pagination={
                'next': '.next, .pagination-next, [rel="next"]',
                'products': '.product, .item, .product-item'
            }
        )
        
        # Social Media Template
        templates['social_media'] = ScrapingTemplate(
            name='Social Media Posts',
            description='Extract posts from social media platforms',
            category='social',
            selectors={
                'posts': '.post, .tweet, .status, .update',
                'username': '.username, .user-name, .author',
                'timestamp': '.timestamp, .time, .date',
                'content': '.content, .post-content, .message',
                'likes': '.likes, .like-count, [aria-label*="like"]',
                'shares': '.shares, .share-count, [aria-label*="share"]',
                'comments': '.comments, .comment-count',
                'media': '.media img, .photo img, .video'
            },
            wait_for='.post, .tweet, .status',
            scroll=True,
            custom_config={
                'rate_limit': 2.0,  # Slower for social media
                'max_scrolls': 20
            }
        )
        
        # News Template
        templates['news'] = ScrapingTemplate(
            name='News Website',
            description='Extract news articles and headlines',
            category='news',
            selectors={
                'headlines': '.headline, .news-title, h2, h3',
                'article_title': 'h1, .article-title',
                'lead_paragraph': '.lead, .summary, .article-summary',
                'article_body': '.article-body, .story-body, .content',
                'author': '.author, .byline, .reporter',
                'publish_date': '.date, .published, time[datetime]',
                'category': '.category, .section, .topic',
                'source': '.source, .outlet'
            },
            wait_for='.article-body, .story-body',
            scroll=False
        )
        
        # Forum Template
        templates['forum'] = ScrapingTemplate(
            name='Forum/Discussion',
            description='Extract forum posts and discussions',
            category='forum',
            selectors={
                'threads': '.thread, .topic, .discussion',
                'title': '.thread-title, .topic-title, h2, h3',
                'author': '.author, .username, .user',
                'posts': '.post, .message, .comment',
                'post_content': '.post-content, .message-body',
                'timestamp': '.date, .timestamp, time',
                'replies': '.replies, .reply-count',
                'views': '.views, .view-count'
            },
            wait_for='.thread, .topic',
            scroll=True,
            pagination={
                'next': '.next, .pagination-next',
                'threads': '.thread, .topic'
            }
        )
        
        # Real Estate Template
        templates['real_estate'] = ScrapingTemplate(
            name='Real Estate Listings',
            description='Extract property listings',
            category='realestate',
            selectors={
                'property_title': '.property-title, h1, .listing-title',
                'price': '.price, .listing-price, .property-price',
                'address': '.address, .location, .property-address',
                'bedrooms': '.bedrooms, .beds, [data-beds]',
                'bathrooms': '.bathrooms, .baths, [data-baths]',
                'area': '.area, .sqft, .size, .property-size',
                'description': '.description, .property-description',
                'features': '.features, .amenities, .property-features',
                'images': '.property-image img, .gallery img',
                'agent': '.agent, .listing-agent'
            },
            wait_for='.property-title, h1',
            scroll=True,
            pagination={
                'next': '.next, .pagination-next',
                'listings': '.property, .listing, .item'
            }
        )
        
        # Job Board Template
        templates['jobs'] = ScrapingTemplate(
            name='Job Board',
            description='Extract job postings',
            category='jobs',
            selectors={
                'job_title': '.job-title, h1, .position',
                'company': '.company, .employer, .organization',
                'location': '.location, .job-location',
                'salary': '.salary, .compensation, .pay',
                'description': '.job-description, .description',
                'requirements': '.requirements, .qualifications',
                'benefits': '.benefits, .perks',
                'posted_date': '.posted-date, .date, time',
                'application_url': '.apply, .application-link, a[href*="apply"]'
            },
            wait_for='.job-title, h1',
            scroll=True,
            pagination={
                'next': '.next, .pagination-next',
                'jobs': '.job, .position, .listing'
            }
        )
        
        # Recipe Template
        templates['recipe'] = ScrapingTemplate(
            name='Recipe Website',
            description='Extract recipes and cooking instructions',
            category='food',
            selectors={
                'recipe_title': '.recipe-title, h1',
                'author': '.author, .chef',
                'prep_time': '.prep-time, .prepare-time',
                'cook_time': '.cook-time, .cooking-time',
                'servings': '.servings, .yield',
                'ingredients': '.ingredients, .ingredient-list',
                'instructions': '.instructions, .steps, .method',
                'nutrition': '.nutrition, .nutritional-info',
                'images': '.recipe-image img, .photo img'
            },
            wait_for='.recipe-title, h1',
            scroll=False
        )
        
        # GitHub Repository Template
        templates['github'] = ScrapingTemplate(
            name='GitHub Repository',
            description='Extract repository information',
            category='development',
            selectors={
                'repo_name': 'h1 strong a',
                'description': 'p.f4',
                'stars': '[href="#stargazers"]',
                'forks': '[href="#forks"]',
                'language': '.repository-lang-stats-graph',
                'readme': '#readme .markdown-body',
                'issues': '[href="#issues"]',
                'pull_requests': '[href="#pull-requests"]',
                'commits': '.commits-list-item'
            },
            wait_for='h1 strong a',
            scroll=False
        )
        
        return templates
    
    def get_template(self, name: str) -> ScrapingTemplate:
        """Get a specific template"""
        return self.templates.get(name)
    
    def list_templates(self, category: str = None) -> List[ScrapingTemplate]:
        """List all templates or templates by category"""
        if category:
            return [t for t in self.templates.values() if t.category == category]
        return list(self.templates.values())
    
    def get_categories(self) -> List[str]:
        """Get all template categories"""
        return list(set(t.category for t in self.templates.values()))
    
    def create_custom_template(self, template_data: Dict[str, Any]) -> ScrapingTemplate:
        """Create a custom template"""
        return ScrapingTemplate(**template_data)
    
    def save_template(self, template: ScrapingTemplate) -> bool:
        """Save a template (in production, save to database)"""
        try:
            self.templates[template.name] = template
            return True
        except Exception as e:
            logger.error(f"Failed to save template: {str(e)}")
            return False
    
    def export_template(self, name: str) -> str:
        """Export template as JSON"""
        template = self.get_template(name)
        if not template:
            return None
        
        return json.dumps({
            'name': template.name,
            'description': template.description,
            'category': template.category,
            'selectors': template.selectors,
            'wait_for': template.wait_for,
            'scroll': template.scroll,
            'pagination': template.pagination,
            'custom_config': template.custom_config
        }, indent=2)
    
    def import_template(self, template_json: str) -> bool:
        """Import template from JSON"""
        try:
            data = json.loads(template_json)
            template = self.create_custom_template(data)
            return self.save_template(template)
        except Exception as e:
            logger.error(f"Failed to import template: {str(e)}")
            return False

# Template validation
def validate_template(template: ScrapingTemplate) -> List[str]:
    """Validate template configuration"""
    errors = []
    
    if not template.name:
        errors.append("Template name is required")
    
    if not template.selectors:
        errors.append("At least one selector is required")
    
    # Validate CSS selectors
    for selector_name, selector in template.selectors.items():
        if not selector:
            errors.append(f"Selector '{selector_name}' is empty")
    
    # Validate pagination selectors if present
    if template.pagination:
        required_pagination_fields = ['next']
        for field in required_pagination_fields:
            if field not in template.pagination:
                errors.append(f"Pagination missing required field: {field}")
    
    return errors

# Template presets for common use cases
TEMPLATE_PRESETS = {
    'quick_blog': {
        'name': 'Quick Blog Extract',
        'selectors': {
            'title': 'h1',
            'content': 'article, .content, .post',
            'author': '.author, .byline'
        }
    },
    'product_info': {
        'name': 'Product Information',
        'selectors': {
            'name': '.product-name, h1',
            'price': '.price, [data-price]',
            'description': '.description'
        }
    },
    'contact_info': {
        'name': 'Contact Information',
        'selectors': {
            'phone': 'a[href*="tel:"], [href*="phone"]',
            'email': 'a[href*="mailto:"], [href*="email"]',
            'address': '.address, .location'
        }
    }
}
