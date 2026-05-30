"""
Production-Grade Data Scraper Service
Integrates all advanced features: selectors, job queue, database, anti-bot
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict

from .advanced_engine import AdvancedScrapingEngine, ScrapingConfig, FieldConfig, SelectorType
from .job_queue import JobManager, JobStatus
from .database_integration import DatabaseManager, DatabaseType, JobRecord, ScrapedRecord

logger = logging.getLogger(__name__)

@dataclass
class ScrapingRequest:
    """Request structure for scraping operations."""
    url: str
    fields: List[Dict[str, Any]]
    options: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.options is None:
            self.options = {}

@dataclass
class ScrapingResponse:
    """Response structure for scraping operations."""
    success: bool
    job_id: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    total_items: int = 0
    execution_time: float = 0.0
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []

class ProductionScraperService:
    """Production-grade scraper service with all advanced features."""
    
    def __init__(self, 
                 db_type: DatabaseType = DatabaseType.POSTGRESQL,
                 db_connection_string: str = None,
                 enable_job_queue: bool = True,
                 enable_database: bool = True):
        
        self.enable_job_queue = enable_job_queue
        self.enable_database = enable_database
        
        # Initialize components
        if enable_job_queue:
            self.job_manager = JobManager()
        
        if enable_database:
            self.db_manager = DatabaseManager(
                db_type=db_type,
                connection_string=db_connection_string
            )
        
        # Anti-bot configuration
        self.user_agents = self._load_user_agents()
        self.proxies = self._load_proxies()
        
        logger.info("ProductionScraperService initialized")
    
    def submit_scraping_job(self, request: ScrapingRequest) -> ScrapingResponse:
        """
        Submit a scraping job to the queue.
        
        Args:
            request: Scraping request configuration
            
        Returns:
            ScrapingResponse with job ID
        """
        try:
            if not self.enable_job_queue:
                # Execute immediately if queue is disabled
                return self._execute_immediately(request)
            
            # Validate request
            validation_errors = self._validate_request(request)
            if validation_errors:
                return ScrapingResponse(
                    success=False,
                    errors=validation_errors
                )
            
            # Prepare configuration
            config = self._prepare_config(request)
            
            # Submit to job queue
            job_id = self.job_manager.submit_job(config)
            
            # Save job to database if enabled
            if self.enable_database:
                job_record = JobRecord(
                    job_id=job_id,
                    config=config,
                    status=JobStatus.PENDING.value,
                    created_at=datetime.utcnow()
                )
                self.db_manager.save_job(job_record)
            
            logger.info(f"Submitted scraping job {job_id} for {request.url}")
            
            return ScrapingResponse(
                success=True,
                job_id=job_id
            )
            
        except Exception as e:
            error_msg = f"Failed to submit scraping job: {str(e)}"
            logger.error(error_msg)
            return ScrapingResponse(
                success=False,
                errors=[error_msg]
            )
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get job status and progress.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status information
        """
        try:
            if not self.enable_job_queue:
                return {"error": "Job queue is disabled"}
            
            # Get status from job manager
            job_info = self.job_manager.get_job_status(job_id)
            
            if not job_info:
                return {"error": "Job not found"}
            
            # Convert to dict
            status_dict = {
                "job_id": job_info.job_id,
                "status": job_info.status.value,
                "created_at": job_info.created_at.isoformat(),
                "started_at": job_info.started_at.isoformat() if job_info.started_at else None,
                "completed_at": job_info.completed_at.isoformat() if job_info.completed_at else None,
                "progress": job_info.progress,
                "current_page": job_info.current_page,
                "total_pages": job_info.total_pages,
                "items_extracted": job_info.items_extracted,
                "error": job_info.error
            }
            
            # Add result if completed
            if job_info.status == JobStatus.SUCCESS and job_info.result:
                status_dict["result"] = job_info.result
            
            return status_dict
            
        except Exception as e:
            error_msg = f"Failed to get job status: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def get_job_results(self, job_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        Get scraping results for a job.
        
        Args:
            job_id: Job identifier
            limit: Maximum number of items to return
            
        Returns:
            Scraping results
        """
        try:
            if not self.enable_database:
                return {"error": "Database is disabled"}
            
            # Get job information
            job_record = self.db_manager.get_job(job_id)
            if not job_record:
                return {"error": "Job not found"}
            
            # Get scraped data
            scraped_data = self.db_manager.get_scraped_data(job_id, limit)
            
            # Convert to response format
            results = {
                "job_id": job_id,
                "job_status": job_record.status,
                "total_items": job_record.total_items,
                "execution_time": job_record.execution_time,
                "items": []
            }
            
            for record in scraped_data:
                results["items"].append({
                    "id": record.id,
                    "url": record.url,
                    "timestamp": record.timestamp,
                    "data": record.data,
                    "screenshot_path": record.screenshot_path,
                    "extraction_time": record.extraction_time
                })
            
            return results
            
        except Exception as e:
            error_msg = f"Failed to get job results: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def scrape_immediately(self, request: ScrapingRequest) -> ScrapingResponse:
        """
        Execute scraping immediately without queue.
        
        Args:
            request: Scraping request configuration
            
        Returns:
            ScrapingResponse with results
        """
        return self._execute_immediately(request)
    
    def _execute_immediately(self, request: ScrapingRequest) -> ScrapingResponse:
        """Execute scraping immediately."""
        start_time = time.time()
        
        try:
            # Validate request
            validation_errors = self._validate_request(request)
            if validation_errors:
                return ScrapingResponse(
                    success=False,
                    errors=validation_errors
                )
            
            # Prepare configuration
            config = self._prepare_config(request)
            
            # Execute scraping
            with AdvancedScrapingEngine(
                headless=config.get('headless', True),
                proxy=config.get('proxy')
            ) as engine:
                
                # Parse configuration
                fields = []
                for field_data in request.fields:
                    field = FieldConfig(
                        name=field_data['name'],
                        selector=field_data['selector'],
                        selector_type=SelectorType(field_data['selector_type']),
                        attribute=field_data.get('attribute'),
                        multiple=field_data.get('multiple', False),
                        required=field_data.get('required', True),
                        transform=field_data.get('transform')
                    )
                    fields.append(field)
                
                scraping_config = ScrapingConfig(
                    url=request.url,
                    fields=fields,
                    wait_for_selector=config.get('wait_for_selector'),
                    wait_timeout=config.get('wait_timeout', 10),
                    infinite_scroll=config.get('infinite_scroll', False),
                    scroll_delay=config.get('scroll_delay', 1.0),
                    max_scrolls=config.get('max_scrolls', 10),
                    pagination=config.get('pagination', False),
                    pagination_selector=config.get('pagination_selector'),
                    pagination_max_pages=config.get('pagination_max_pages', 10),
                    screenshot=config.get('screenshot', False),
                    capture_network=config.get('capture_network', False),
                    delay_between_requests=config.get('delay_between_requests', 1.0),
                    retry_attempts=config.get('retry_attempts', 3),
                    user_agent=config.get('user_agent')
                )
                
                # Execute scraping
                result = engine.scrape(scraping_config)
                
                # Convert to response format
                response = ScrapingResponse(
                    success=result.success,
                    data=[asdict(item) for item in result.items],
                    total_items=result.total_items,
                    execution_time=result.execution_time,
                    errors=result.errors,
                    warnings=result.warnings
                )
                
                # Save to database if enabled
                if self.enable_database and result.success:
                    self._save_immediate_results(request.url, result.items)
                
                return response
                
        except Exception as e:
            error_msg = f"Immediate scraping failed: {str(e)}"
            logger.error(error_msg)
            return ScrapingResponse(
                success=False,
                errors=[error_msg],
                execution_time=time.time() - start_time
            )
    
    def _save_immediate_results(self, url: str, items: List[Any]):
        """Save immediate scraping results to database."""
        try:
            # Create a temporary job ID for immediate results
            job_id = f"immediate_{int(time.time())}"
            
            # Save job record
            job_record = JobRecord(
                job_id=job_id,
                config={"url": url, "immediate": True},
                status="completed",
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                total_items=len(items)
            )
            self.db_manager.save_job(job_record)
            
            # Save scraped data
            scraped_records = []
            for item in items:
                record = ScrapedRecord(
                    job_id=job_id,
                    url=item.url,
                    timestamp=item.timestamp,
                    data=item.data,
                    screenshot_path=item.screenshot_path,
                    raw_html=item.raw_html,
                    extraction_time=item.extraction_time,
                    created_at=datetime.utcnow()
                )
                scraped_records.append(record)
            
            self.db_manager.save_scraped_data(scraped_records)
            
        except Exception as e:
            logger.error(f"Failed to save immediate results: {e}")
    
    def list_jobs(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List jobs with optional status filter."""
        try:
            if self.enable_database:
                # Get from database
                job_records = self.db_manager.list_jobs(status, limit)
                return [asdict(record) for record in job_records]
            elif self.enable_job_queue:
                # Get from job manager
                job_infos = self.job_manager.list_jobs(
                    JobStatus(status) if status else None,
                    limit
                )
                return [asdict(info) for info in job_infos]
            else:
                return []
        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        try:
            if not self.enable_job_queue:
                return False
            
            success = self.job_manager.cancel_job(job_id)
            
            # Update database if enabled
            if success and self.enable_database:
                job_record = self.db_manager.get_job(job_id)
                if job_record:
                    job_record.status = JobStatus.REVOKED.value
                    job_record.completed_at = datetime.utcnow()
                    self.db_manager.save_job(job_record)
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to cancel job: {e}")
            return False
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job and its data."""
        try:
            # Delete from job manager
            if self.enable_job_queue:
                self.job_manager.delete_job(job_id)
            
            # Delete from database
            if self.enable_database:
                self.db_manager.delete_job(job_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete job: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get overall scraping statistics."""
        try:
            stats = {}
            
            if self.enable_database:
                db_stats = self.db_manager.get_statistics()
                stats.update(db_stats)
            
            if self.enable_job_queue:
                queue_stats = self.job_manager.get_job_statistics()
                stats.update({
                    'queue_stats': queue_stats
                })
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def _validate_request(self, request: ScrapingRequest) -> List[str]:
        """Validate scraping request."""
        errors = []
        
        # Validate URL
        if not request.url or not request.url.startswith(('http://', 'https://')):
            errors.append("Valid URL is required")
        
        # Validate fields
        if not request.fields:
            errors.append("At least one field must be specified")
        else:
            for i, field in enumerate(request.fields):
                if not field.get('name'):
                    errors.append(f"Field {i+1}: name is required")
                if not field.get('selector'):
                    errors.append(f"Field {i+1}: selector is required")
                if field.get('selector_type') not in ['css', 'xpath']:
                    errors.append(f"Field {i+1}: selector_type must be 'css' or 'xpath'")
        
        return errors
    
    def _prepare_config(self, request: ScrapingRequest) -> Dict[str, Any]:
        """Prepare configuration for scraping engine."""
        config = {
            'url': request.url,
            'fields': request.fields,
            'headless': request.options.get('headless', True),
            'proxy': request.options.get('proxy'),
            'wait_for_selector': request.options.get('wait_for_selector'),
            'wait_timeout': request.options.get('wait_timeout', 10),
            'infinite_scroll': request.options.get('infinite_scroll', False),
            'scroll_delay': request.options.get('scroll_delay', 1.0),
            'max_scrolls': request.options.get('max_scrolls', 10),
            'pagination': request.options.get('pagination', False),
            'pagination_selector': request.options.get('pagination_selector'),
            'pagination_max_pages': request.options.get('pagination_max_pages', 10),
            'screenshot': request.options.get('screenshot', False),
            'capture_network': request.options.get('capture_network', False),
            'delay_between_requests': request.options.get('delay_between_requests', 1.0),
            'retry_attempts': request.options.get('retry_attempts', 3),
            'user_agent': request.options.get('user_agent') or self._get_random_user_agent()
        }
        
        return config
    
    def _load_user_agents(self) -> List[str]:
        """Load user agents for rotation."""
        return [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0'
        ]
    
    def _load_proxies(self) -> List[str]:
        """Load proxy servers."""
        # Could be loaded from config file or database
        return []
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent."""
        import random
        return random.choice(self.user_agents)
    
    def close(self):
        """Close resources."""
        if hasattr(self, 'db_manager') and self.db_manager:
            self.db_manager.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
