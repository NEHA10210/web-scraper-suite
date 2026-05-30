"""
Celery tasks for asynchronous scraping
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any
from celery import Celery
from celery.result import AsyncResult
from .scraper_engine import AdvancedScraper, ScrapingConfig, ExportFormat, ScrapingStatus

logger = logging.getLogger(__name__)

# Initialize Celery
celery_app = Celery(
    'scraper_tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0',
    include=['data_scraper_pro.tasks']
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes
    task_soft_time_limit=540,  # 9 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

@celery_app.task(bind=True)
def scrape_website_task(self, job_id: str, config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronous website scraping task
    """
    try:
        # Update job status to running
        update_job_status(job_id, ScrapingStatus.RUNNING)
        
        # Convert config dict to ScrapingConfig
        config = ScrapingConfig(**config_dict)
        
        # Initialize scraper
        scraper = AdvancedScraper()
        
        # Perform scraping
        result = await scraper.scrape(config)
        
        # Export data in requested format
        exported_data = scraper.export_data(result, config.export_format)
        
        # Update job with results
        update_job_result(job_id, {
            'data': result,
            'exported': exported_data,
            'format': config.export_format.value
        })
        
        # Update status to completed
        update_job_status(job_id, ScrapingStatus.COMPLETED)
        
        return {
            'job_id': job_id,
            'status': ScrapingStatus.COMPLETED.value,
            'result': result,
            'exported_data': exported_data
        }
        
    except Exception as e:
        logger.error(f"Scraping task failed for job {job_id}: {str(e)}")
        
        # Update job with error
        update_job_error(job_id, str(e))
        update_job_status(job_id, ScrapingStatus.FAILED)
        
        # Retry if configured
        if self.request.retries < config.retry_count:
            logger.info(f"Retrying job {job_id}, attempt {self.request.retries + 1}")
            raise self.retry(countdown=60 * (self.request.retries + 1))
        
        return {
            'job_id': job_id,
            'status': ScrapingStatus.FAILED.value,
            'error': str(e)
        }

@celery_app.task
def cleanup_old_jobs():
    """
    Clean up old completed jobs
    """
    # Implementation for cleaning up old jobs
    pass

def update_job_status(job_id: str, status: ScrapingStatus):
    """Update job status in database"""
    from .scraper_engine import ScrapingJob, Session
    
    session = Session()
    try:
        job = session.query(ScrapingJob).filter_by(id=job_id).first()
        if job:
            job.status = status.value
            if status == ScrapingStatus.RUNNING:
                job.started_at = datetime.utcnow()
            elif status in [ScrapingStatus.COMPLETED, ScrapingStatus.FAILED]:
                job.completed_at = datetime.utcnow()
            session.commit()
    finally:
        session.close()

def update_job_result(job_id: str, result: Dict[str, Any]):
    """Update job result in database"""
    from .scraper_engine import ScrapingJob, Session
    
    session = Session()
    try:
        job = session.query(ScrapingJob).filter_by(id=job_id).first()
        if job:
            job.result = json.dumps(result)
            session.commit()
    finally:
        session.close()

def update_job_error(job_id: str, error: str):
    """Update job error in database"""
    from .scraper_engine import ScrapingJob, Session
    
    session = Session()
    try:
        job = session.query(ScrapingJob).filter_by(id=job_id).first()
        if job:
            job.error = error
            session.commit()
    finally:
        session.close()

def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get job status and results"""
    from .scraper_engine import ScrapingJob, Session
    
    session = Session()
    try:
        job = session.query(ScrapingJob).filter_by(id=job_id).first()
        if job:
            result = {
                'job_id': job.id,
                'status': job.status,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'started_at': job.started_at.isoformat() if job.started_at else None,
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                'retry_count': job.retry_count
            }
            
            if job.result:
                result['result'] = json.loads(job.result)
            
            if job.error:
                result['error'] = job.error
            
            return result
        else:
            return {'error': 'Job not found'}
    finally:
        session.close()

def cancel_job(job_id: str) -> bool:
    """Cancel a running job"""
    try:
        # Revoke the task
        celery_app.control.revoke(job_id, terminate=True)
        
        # Update database
        update_job_status(job_id, ScrapingStatus.CANCELLED)
        
        return True
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {str(e)}")
        return False
