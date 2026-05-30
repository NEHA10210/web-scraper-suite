"""
Enhanced Text Scraper with NLP Processing
Advanced text extraction, cleaning, and analysis
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from .scraper_engine import AdvancedScraper, ScrapingConfig
from .text_processor import AdvancedTextProcessor, ProcessedContent
import json

logger = logging.getLogger(__name__)

class EnhancedTextScraper:
    def __init__(self):
        self.scraper = AdvancedScraper()
        self.text_processor = AdvancedTextProcessor()
    
    async def scrape_text_advanced(self, url: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enhanced text scraping with NLP processing
        """
        try:
            # Default configuration for text scraping
            scrape_config = ScrapingConfig(
                url=url,
                javascript=True,
                scroll=True,
                timeout=30000,
                delay=1.0,
                screenshots=False,
                save_to_db=False
            )
            
            # Override with custom config
            if config:
                for key, value in config.items():
                    if hasattr(scrape_config, key):
                        setattr(scrape_config, key, value)
            
            # Scrape the page
            logger.info(f"Starting enhanced text scraping for: {url}")
            raw_data = await self.scraper.scrape(scrape_config)
            
            # Process the text content
            if raw_data.get('success') and raw_data.get('content'):
                processed_content = self.text_processor.process_html(
                    raw_data['content'].get('html', ''),
                    url
                )
                
                # Convert to structured output
                structured_output = self._create_structured_output(processed_content, raw_data)
                
                return {
                    'success': True,
                    'url': url,
                    'processed_content': structured_output,
                    'raw_data': raw_data,
                    'timestamp': datetime.utcnow().isoformat()
                }
            else:
                return {
                    'success': False,
                    'error': raw_data.get('error', 'Failed to scrape content'),
                    'url': url
                }
                
        except Exception as e:
            logger.error(f"Error in enhanced text scraping: {str(e)}")
            return {
                'success': False,
                'error': f'Enhanced scraping failed: {str(e)}',
                'url': url
            }
    
    def _create_structured_output(self, content: ProcessedContent, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create clean structured output without single text block"""
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
            'metadata': content.metadata,
            'statistics': self._create_statistics(content)
        }
    
    def _create_clean_text(self, content: ProcessedContent) -> str:
        """Create a clean text version"""
        sections = []
        
        # Add title
        if content.title:
            sections.append(f"# {content.title}\n")
        
        # Add headings and content
        current_level = 0
        for heading in content.headings:
            # Add heading
            level_prefix = "#" * heading['level']
            sections.append(f"\n{level_prefix} {heading['text']}\n")
            
            # Find paragraphs that might belong to this section
            # This is a simplified approach - in reality, you'd need more sophisticated section mapping
            sections.extend([f"{p}\n" for p in content.paragraphs[:3]])  # Add first few paragraphs as example
        
        # Add remaining paragraphs
        if content.paragraphs:
            sections.append("\n## Content\n")
            sections.extend([f"{p}\n" for p in content.paragraphs])
        
        return "".join(sections)
    
    def _create_statistics(self, content: ProcessedContent) -> Dict[str, Any]:
        """Create content statistics"""
        return {
            'content_stats': {
                'total_headings': len(content.headings),
                'total_paragraphs': len(content.paragraphs),
                'total_lists': len(content.lists),
                'total_keywords': len(content.keywords),
                'total_entities': len(content.entities),
                'content_type': content.classification['type'],
                'confidence': content.classification['confidence']
            },
            'quality_metrics': {
                'has_title': bool(content.title),
                'has_headings': len(content.headings) > 0,
                'has_structured_content': len(content.headings) > 0 and len(content.paragraphs) > 0,
                'readability_score': content.readability['flesch_score'],
                'difficulty_level': content.readability['difficulty'],
                'seo_score': self._calculate_seo_score(content.seo)
            }
        }
    
    def _calculate_seo_score(self, seo_data: Dict[str, Any]) -> int:
        """Calculate SEO score (0-100)"""
        score = 0
        
        # Title optimization (30 points)
        if seo_data['title']['present']:
            score += 10
        if seo_data['title']['optimal']:
            score += 20
        
        # Meta description (25 points)
        if seo_data['meta_description']['present']:
            score += 10
        if seo_data['meta_description']['optimal']:
            score += 15
        
        # Headings structure (25 points)
        if seo_data['headings']['has_h1']:
            score += 15
        if seo_data['headings']['h1_count'] == 1:
            score += 10
        
        # Content length (20 points)
        if seo_data['content']['word_count'] >= 300:
            score += 10
        if seo_data['content']['word_count'] >= 600:
            score += 10
        
        return min(score, 100)
    
    async def scrape_text_sync(self, url: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Synchronous version for smaller tasks"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = await self.scrape_text_advanced(url, config)
            return result
        finally:
            loop.close()
    
    def export_processed_content(self, content: Dict[str, Any], format: str = 'json') -> str:
        """Export processed content in different formats"""
        if format == 'json':
            return json.dumps(content, indent=2, ensure_ascii=False)
        
        elif format == 'markdown':
            return self._export_to_markdown(content)
        
        elif format == 'text':
            return content.get('clean_text', '')
        
        elif format == 'csv':
            return self._export_to_csv(content)
        
        else:
            return json.dumps(content, indent=2)
    
    def _export_to_markdown(self, content: Dict[str, Any]) -> str:
        """Export to Markdown format"""
        md = []
        
        # Title
        if content.get('title'):
            md.append(f"# {content['title']}\n")
        
        # Metadata
        metadata = content.get('metadata', {})
        md.append("## Metadata\n")
        md.append(f"- **URL:** {metadata.get('url', 'N/A')}")
        md.append(f"- **Processed:** {metadata.get('processed_at', 'N/A')}")
        md.append(f"- **Word Count:** {metadata.get('word_count', 0)}")
        md.append(f"- **Reading Time:** {content.get('readability', {}).get('reading_time_minutes', 0)} minutes\n")
        
        # Summary
        summary = content.get('summary', {})
        if summary.get('short'):
            md.append("## Summary\n")
            md.append(f"{summary['short']}\n")
        
        # Keywords
        keywords = content.get('keywords', [])
        if keywords:
            md.append("## Keywords\n")
            for keyword in keywords[:10]:
                md.append(f"- **{keyword['keyword']}** (density: {keyword['density']}%)")
            md.append("")
        
        # Entities
        entities = content.get('entities', [])
        if entities:
            md.append("## Named Entities\n")
            current_type = None
            for entity in entities[:15]:
                if entity['label'] != current_type:
                    current_type = entity['label']
                    md.append(f"\n### {entity['label']}")
                md.append(f"- {entity['text']}")
            md.append("")
        
        # Content structure
        headings = content.get('headings', [])
        if headings:
            md.append("## Content Structure\n")
            for heading in headings:
                level_prefix = "#" * (heading['level'] + 1)
                md.append(f"{level_prefix} {heading['text']}")
            md.append("")
        
        # Main content
        paragraphs = content.get('paragraphs', [])
        if paragraphs:
            md.append("## Content\n")
            for para in paragraphs:
                md.append(f"{para}\n")
        
        return "\n".join(md)
    
    def _export_to_csv(self, content: Dict[str, Any]) -> str:
        """Export to CSV format"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['Section', 'Content', 'Type', 'Metadata'])
        
        # Title
        if content.get('title'):
            writer.writerow(['Title', content['title'], 'text', 'main'])
        
        # Headings
        for heading in content.get('headings', []):
            writer.writerow(['Heading', heading['text'], 'h' + str(heading['level']), f"level:{heading['level']}"])
        
        # Paragraphs
        for i, para in enumerate(content.get('paragraphs', [])):
            writer.writerow(['Paragraph', para, 'text', f'para:{i+1}'])
        
        # Keywords
        for keyword in content.get('keywords', []):
            writer.writerow(['Keyword', keyword['keyword'], 'keyword', f"density:{keyword['density']}%"])
        
        # Entities
        for entity in content.get('entities', []):
            writer.writerow(['Entity', entity['text'], entity['label'], f"count:{entity.get('count', 1)}"])
        
        return output.getvalue()
