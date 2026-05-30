"""
Job Queue System for Background Scraping Tasks
Uses Celery for distributed task processing
"""

import json
import logging
import os
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

from celery import Celery
from celery.result import AsyncResult
from redis import Redis

logger = logging.getLogger(__name__)

# Initialize Celery
celery_app = Celery('scraper_tasks')
celery_app.config_from_object({
    'broker_url': os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    'result_backend': os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    'task_serializer': 'json',
    'accept_content': ['json'],
    'result_serializer': 'json',
    'timezone': 'UTC',
    'enable_utc': True,
    'task_track_started': True,
    'task_routes': {
        'data_scraper.job_queue.scrape_task': {'queue': 'scraping'},
    },
    'worker_prefetch_multiplier': 1,
    'task_acks_late': True,
})

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"

@dataclass
class JobInfo:
    """Job information and metadata."""
    job_id: str
    status: JobStatus
    config: Dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: float = 0.0
    current_page: int = 0
    total_pages: int = 0
    items_extracted: int = 0

class JobManager:
    """Manages scraping jobs in the queue."""
    
    def __init__(self):
        self.redis_client = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=1  # Separate DB for job metadata
        )
    
    def submit_job(self, config: Dict[str, Any]) -> str:
        """
        Submit a new scraping job to the queue.
        
        Args:
            config: Scraping configuration
            
        Returns:
            Job ID
        """
        # Create job metadata
        job_id = f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(str(config)) % 10000}"
        
        job_info = JobInfo(
            job_id=job_id,
            status=JobStatus.PENDING,
            config=config,
            created_at=datetime.utcnow()
        )
        
        # Store job metadata in Redis
        self._store_job_info(job_info)
        
        # Submit task to Celery
        task = scrape_task.delay(job_id, config)
        
        # Map Celery task ID to our job ID
        self.redis_client.set(f"task_map:{task.id}", job_id)
        self.redis_client.set(f"job_task:{job_id}", task.id)
        
        logger.info(f"Submitted job {job_id} with task {task.id}")
        
        return job_id
    
    def get_job_status(self, job_id: str) -> Optional[JobInfo]:
        """
        Get job status and information.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobInfo or None if not found
        """
        # Get job info from Redis
        job_data = self.redis_client.get(f"job:{job_id}")
        if not job_data:
            return None
        
        job_dict = json.loads(job_data)
        
        # Convert string timestamps back to datetime
        for key in ['created_at', 'started_at', 'completed_at']:
            if job_dict.get(key):
                job_dict[key] = datetime.fromisoformat(job_dict[key])
        
        # Convert status back to enum
        job_dict['status'] = JobStatus(job_dict['status'])
        
        return JobInfo(**job_dict)
    
    def update_job_progress(self, job_id: str, progress: float, 
                           current_page: int = 0, total_pages: int = 0,
                           items_extracted: int = 0):
        """Update job progress."""
        job_info = self.get_job_status(job_id)
        if job_info:
            job_info.progress = progress
            job_info.current_page = current_page
            job_info.total_pages = total_pages
            job_info.items_extracted = items_extracted
            self._store_job_info(job_info)
    
    def update_job_status(self, job_id: str, status: JobStatus, 
                         result: Optional[Dict[str, Any]] = None,
                         error: Optional[str] = None):
        """Update job status."""
        job_info = self.get_job_status(job_id)
        if job_info:
            job_info.status = status
            
            if status == JobStatus.RUNNING and not job_info.started_at:
                job_info.started_at = datetime.utcnow()
            elif status in [JobStatus.SUCCESS, JobStatus.FAILURE]:
                job_info.completed_at = datetime.utcnow()
                if result:
                    job_info.result = result
                if error:
                    job_info.error = error
            
            self._store_job_info(job_info)
    
    def list_jobs(self, status: Optional[JobStatus] = None, 
                  limit: int = 50) -> List[JobInfo]:
        """List jobs with optional status filter."""
        job_keys = self.redis_client.keys("job:*")
        jobs = []
        
        for key in job_keys[:limit]:
            job_id = key.decode('utf-8').split(':', 1)[1]
            job_info = self.get_job_status(job_id)
            if job_info and (status is None or job_info.status == status):
                jobs.append(job_info)
        
        # Sort by creation time (newest first)
        jobs.sort(key=lambda x: x.created_at, reverse=True)
        
        return jobs
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        # Get Celery task ID
        task_id = self.redis_client.get(f"job_task:{job_id}")
        if not task_id:
            return False
        
        task_id = task_id.decode('utf-8')
        
        # Revoke the Celery task
        celery_app.control.revoke(task_id, terminate=True)
        
        # Update job status
        self.update_job_status(job_id, JobStatus.REVOKED)
        
        logger.info(f"Cancelled job {job_id}")
        
        return True
    
    def delete_job(self, job_id: str) -> bool:
        """Delete job metadata."""
        # Get Celery task ID
        task_id = self.redis_client.get(f"job_task:{job_id}")
        if task_id:
            task_id = task_id.decode('utf-8')
            # Remove task mapping
            self.redis_client.delete(f"task_map:{task_id}")
        
        # Remove job data
        self.redis_client.delete(f"job:{job_id}")
        self.redis_client.delete(f"job_task:{job_id}")
        
        logger.info(f"Deleted job {job_id}")
        
        return True
    
    def get_job_statistics(self) -> Dict[str, Any]:
        """Get overall job statistics."""
        jobs = self.list_jobs()
        
        stats = {
            'total_jobs': len(jobs),
            'by_status': {},
            'recent_success': 0,
            'recent_failure': 0,
            'avg_execution_time': 0,
            'total_items_extracted': 0
        }
        
        # Count by status
        for status in JobStatus:
            stats['by_status'][status.value] = len([j for j in jobs if j.status == status])
        
        # Recent jobs (last 24 hours)
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_jobs = [j for j in jobs if j.created_at > recent_cutoff]
        
        stats['recent_success'] = len([j for j in recent_jobs if j.status == JobStatus.SUCCESS])
        stats['recent_failure'] = len([j for j in recent_jobs if j.status == JobStatus.FAILURE])
        
        # Calculate average execution time
        completed_jobs = [j for j in jobs if j.completed_at and j.started_at]
        if completed_jobs:
            total_time = sum([(j.completed_at - j.started_at).total_seconds() for j in completed_jobs])
            stats['avg_execution_time'] = total_time / len(completed_jobs)
        
        # Total items extracted
        stats['total_items_extracted'] = sum([j.items_extracted for j in jobs])
        
        return stats
    
    def _store_job_info(self, job_info: JobInfo):
        """Store job information in Redis."""
        job_dict = asdict(job_info)
        
        # Convert datetime to string for JSON serialization
        for key in ['created_at', 'started_at', 'completed_at']:
            if job_dict.get(key):
                job_dict[key] = job_dict[key].isoformat()
        
        # Convert enum to string
        job_dict['status'] = job_dict['status'].value
        
        # Store with TTL (30 days)
        self.redis_client.setex(
            f"job:{job_info.job_id}",
            timedelta(days=30),
            json.dumps(job_dict)
        )

# Celery task definition
@celery_app.task(bind=True)
def scrape_task(self, job_id: str, config: Dict[str, Any]):
    """
    Celery task for executing scraping jobs.
    
    Args:
        job_id: Job identifier
        config: Scraping configuration
        
    Returns:
        Scraping result
    """
    from .advanced_engine import AdvancedScrapingEngine, ScrapingConfig, FieldConfig, SelectorType
    
    job_manager = JobManager()
    
    try:
        # Update job status to running
        job_manager.update_job_status(job_id, JobStatus.RUNNING)
        
        # Parse configuration
        fields = []
        for field_data in config.get('fields', []):
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
            url=config['url'],
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
        with AdvancedScrapingEngine(
            headless=config.get('headless', True),
            proxy=config.get('proxy')
        ) as engine:
            
            # Update progress
            job_manager.update_job_progress(job_id, 0.1)
            
            result = engine.scrape(scraping_config)
            
            # Update progress
            job_manager.update_job_progress(
                job_id, 1.0,
                items_extracted=result.total_items
            )
            
            # Convert result to dict for JSON serialization
            result_dict = {
                'success': result.success,
                'total_items': result.total_items,
                'pages_scraped': result.pages_scraped,
                'execution_time': result.execution_time,
                'errors': result.errors,
                'warnings': result.warnings,
                'items': [asdict(item) for item in result.items]
            }
            
            # Update job status
            if result.success:
                job_manager.update_job_status(job_id, JobStatus.SUCCESS, result=result_dict)
            else:
                job_manager.update_job_status(
                    job_id, JobStatus.FAILURE,
                    error='; '.join(result.errors)
                )
            
            return result_dict
    
    except Exception as e:
        error_msg = f"Scraping task failed: {str(e)}"
        logger.error(error_msg)
        
        # Update job status
        job_manager.update_job_status(job_id, JobStatus.FAILURE, error=error_msg)
        
        # Re-raise for Celery to handle
        raise
