"""
Enhanced Service Methods for DataScraperService
These methods extend the existing service with intelligent scraping capabilities.
"""

import re
from datetime import datetime
from bs4 import BeautifulSoup
from .service import TextResult, TextStats, MetadataExtractor


def _run_enhanced_text_pipeline(self, url: str, soup: BeautifulSoup, logs: list = None) -> dict:
    """Enhanced text extraction with quality validation."""
    if logs is None:
        logs = []
        
    try:
        from .enhanced_text_extractor import EnhancedTextExtractor
        
        # Extract metadata
        metadata = MetadataExtractor.extract(soup, url)
        
        # Use enhanced text extractor
        extractor = EnhancedTextExtractor()
        text, extraction_metadata = extractor.extract(soup, url)
        
        # Calculate stats
        stats = _calculate_text_stats(self, text)
        
        # Create result
        result = TextResult(url=url, title=metadata.title, text=text, stats=stats)
        
        # Validate content quality
        quality_issues = []
        warnings = []
        
        if stats.word_count < 50:
            quality_issues.append("Very low word count")
            warnings.append("Low content extracted (less than 50 words)")
        elif stats.word_count < 100:
            quality_issues.append("Low word count")
            warnings.append("Limited content extracted (less than 100 words)")
        
        if extraction_metadata.get('quality_score', 1.0) < 0.5:
            quality_issues.append("Low content quality detected")
            warnings.append("Content quality may be poor")
        
        # Save if content is meaningful
        saved_files = []
        if text.strip() and stats.word_count >= 20:
            saved_files = self._storage.save_text(result)
        else:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("Insufficient text content extracted from %s.", url)
        
        logs.append(f"Extracted {stats.word_count} words with quality score {extraction_metadata.get('quality_score', 0):.2f}")
        
        return {
            "type": "text",
            "success": True,
            "content": result.to_dict(),
            "saved_files": saved_files,
            "timestamp": result.timestamp,
            "logs": logs,
            "warnings": warnings,
            "extraction_metadata": extraction_metadata,
            "quality_issues": quality_issues
        }
        
    except Exception:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Enhanced text pipeline failed for %s.", url)
        return {"error": "Text scraping failed due to an internal error."}


def _run_image_pipeline(self, url: str, soup: BeautifulSoup, logs: list = None) -> dict:
    """Enhanced image pipeline with logging."""
    if logs is None:
        logs = []
        
    try:
        from .service import ImageExtractor, ImageResult
        
        images = ImageExtractor.extract(soup, url)
        downloaded = self._downloader.download_all(images)
        
        total_bytes = sum(img.size_bytes for img in downloaded)
        result = ImageResult(
            total_found=len(images),
            downloaded=len(downloaded),
            total_size_mb=total_bytes / (1024 * 1024),
            downloaded_images=[img.to_dict() for img in downloaded],
        )
        
        result.saved_files = self._storage.save_image_manifest(url, result)
        
        logs.append(f"Found {len(images)} images, downloaded {len(downloaded)}")
        
        return {
            "type": "images",
            "success": True,
            "images": result.to_dict(),
            "saved_files": result.saved_files,
            "timestamp": result.timestamp,
            "logs": logs
        }
        
    except Exception:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Image pipeline failed for %s.", url)
        return {"error": "Image scraping failed due to an internal error."}


def _combine_results(self, text_result: dict, image_result: dict, logs: list = None) -> dict:
    """Combine text and image results."""
    if logs is None:
        logs = []
        
    combined_logs = logs
    combined_logs.extend(text_result.get('logs', []))
    combined_logs.extend(image_result.get('logs', []))
    
    warnings = text_result.get('warnings', []) + image_result.get('warnings', [])
    
    return {
        "success": True,
        "type": "both",
        "text_data": text_result,
        "image_data": image_result,
        "timestamp": datetime.now().isoformat(),
        "logs": combined_logs,
        "warnings": warnings
    }


def _combine_crawled_results(self, crawled_results: list, logs: list = None) -> dict:
    """Combine results from multiple crawled pages."""
    if not crawled_results:
        return None
        
    if logs is None:
        logs = []
        
    # Combine all text content
    combined_text = []
    total_word_count = 0
    total_char_count = 0
    all_warnings = []
    
    for result in crawled_results:
        content = result.get('content', {})
        if content.get('text'):
            # Add source information
            source_title = result.get('source_title', 'Untitled')
            source_url = result.get('source_url', '')
            combined_text.append(f"\n=== {source_title} ===\n{content['text']}")
            
            total_word_count += content.get('word_count', 0)
            total_char_count += content.get('char_count', 0)
        
        all_warnings.extend(result.get('warnings', []))
    
    if not combined_text:
        logs.append("No meaningful content found in crawled pages")
        return None
    
    final_text = '\n'.join(combined_text)
    
    # Create combined result
    combined_stats = TextStats(
        word_count=total_word_count,
        char_count=total_char_count,
        line_count=len(final_text.split('\n')),
        paragraph_count=len([p for p in final_text.split('\n\n') if p.strip()]),
        sentence_count=len([s for s in final_text.split('. ') if s.strip()]),
        avg_words_per_sentence=total_word_count / len([s for s in final_text.split('. ') if s.strip()]) if final_text else 0
    )
    
    combined_result = TextResult(
        url="multiple_pages",
        title=f"Combined Content from {len(crawled_results)} Pages",
        text=final_text,
        stats=combined_stats
    )
    
    logs.append(f"Combined content from {len(crawled_results)} pages: {total_word_count} total words")
    
    return {
        "type": "text",
        "success": True,
        "content": combined_result.to_dict(),
        "crawled_pages": len(crawled_results),
        "sources": [
            {
                "url": r.get('source_url', ''),
                "title": r.get('source_title', ''),
                "word_count": r.get('content', {}).get('word_count', 0)
            }
            for r in crawled_results
        ],
        "timestamp": datetime.now().isoformat(),
        "logs": logs,
        "warnings": all_warnings
    }


def _calculate_text_stats(self, text: str) -> TextStats:
    """Calculate text statistics."""
    if not text:
        return TextStats()
    
    words = text.split()
    
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text)
        if s.strip()
    ]
    
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    
    avg_words = (
        sum(len(s.split()) for s in sentences) / len(sentences)
        if sentences else 0.0
    )
    
    return TextStats(
        word_count=len(words),
        char_count=len(text),
        line_count=len(text.split('\n')),
        paragraph_count=len(paragraphs),
        sentence_count=len(sentences),
        avg_words_per_sentence=round(avg_words, 1),
    )
