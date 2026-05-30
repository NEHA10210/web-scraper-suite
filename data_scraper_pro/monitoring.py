"""
Monitoring and logging system for the Data Scraper
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import redis
import pymongo
from sqlalchemy import create_engine, Column, String, DateTime, Integer, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()

class ScrapingLog(Base):
    __tablename__ = 'scraping_logs'
    
    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False)
    user_id = Column(String)
    url = Column(String, nullable=False)
    status = Column(String, nullable=False)
    duration = Column(Float)
    data_size = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class PerformanceMetrics(Base):
    __tablename__ = 'performance_metrics'
    
    id = Column(String, primary_key=True)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)
    tags = Column(Text)  # JSON string
    timestamp = Column(DateTime, default=datetime.utcnow)

@dataclass
class JobMetrics:
    job_id: str
    start_time: datetime
    end_time: Optional[datetime]
    status: str
    url: str
    user_id: str
    duration: Optional[float]
    data_size: int
    error_count: int
    retry_count: int

class MonitoringManager:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
        self.mongo_client = pymongo.MongoClient('mongodb://localhost:27017/')
        self.db_name = 'scraper_monitoring'
        
        # Database setup
        self.engine = create_engine('sqlite:///scraper_monitoring.db')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
        # In-memory metrics for real-time monitoring
        self.active_jobs = {}
        self.recent_metrics = deque(maxlen=1000)
        self.error_counts = defaultdict(int)
        self.domain_counts = defaultdict(int)
        
    def log_job_start(self, job_id: str, config: Dict[str, Any]):
        """Log job start"""
        try:
            log_entry = ScrapingLog(
                id=f"{job_id}_start",
                job_id=job_id,
                user_id=config.get('user_id', 'anonymous'),
                url=config['url'],
                status='started',
                created_at=datetime.utcnow()
            )
            
            session = self.Session()
            session.add(log_entry)
            session.commit()
            session.close()
            
            # Track active job
            self.active_jobs[job_id] = {
                'start_time': datetime.utcnow(),
                'url': config['url'],
                'user_id': config.get('user_id', 'anonymous')
            }
            
            # Update domain count
            from urllib.parse import urlparse
            domain = urlparse(config['url']).netloc
            self.domain_counts[domain] += 1
            
            # Store in Redis for real-time monitoring
            self.redis_client.hset(
                f"job:{job_id}",
                mapping={
                    'status': 'started',
                    'start_time': datetime.utcnow().isoformat(),
                    'url': config['url'],
                    'user_id': config.get('user_id', 'anonymous')
                }
            )
            
            # Set expiration for Redis key (24 hours)
            self.redis_client.expire(f"job:{job_id}", 86400)
            
            logger.info(f"Job {job_id} started for URL: {config['url']}")
            
        except Exception as e:
            logger.error(f"Failed to log job start: {str(e)}")
    
    def log_job_complete(self, job_id: str, result: Dict[str, Any]):
        """Log job completion"""
        try:
            # Get job start time
            job_info = self.active_jobs.get(job_id, {})
            start_time = job_info.get('start_time', datetime.utcnow())
            
            # Calculate duration
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            # Calculate data size
            data_size = len(json.dumps(result).encode('utf-8'))
            
            log_entry = ScrapingLog(
                id=f"{job_id}_complete",
                job_id=job_id,
                user_id=job_info.get('user_id', 'anonymous'),
                url=job_info.get('url', ''),
                status='completed',
                duration=duration,
                data_size=data_size,
                created_at=datetime.utcnow()
            )
            
            session = self.Session()
            session.add(log_entry)
            session.commit()
            session.close()
            
            # Update active jobs
            if job_id in self.active_jobs:
                self.active_jobs[job_id]['end_time'] = datetime.utcnow()
                self.active_jobs[job_id]['duration'] = duration
                self.active_jobs[job_id]['data_size'] = data_size
            
            # Update Redis
            self.redis_client.hset(
                f"job:{job_id}",
                mapping={
                    'status': 'completed',
                    'end_time': datetime.utcnow().isoformat(),
                    'duration': duration,
                    'data_size': data_size
                }
            )
            
            # Record performance metrics
            self._record_performance_metric('job_duration', duration, {
                'job_id': job_id,
                'user_id': job_info.get('user_id', 'anonymous')
            })
            
            self._record_performance_metric('data_size', data_size, {
                'job_id': job_id,
                'url': job_info.get('url', '')
            })
            
            # Clean up active jobs after completion
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            
            logger.info(f"Job {job_id} completed in {duration:.2f}s, size: {data_size} bytes")
            
        except Exception as e:
            logger.error(f"Failed to log job completion: {str(e)}")
    
    def log_job_error(self, job_id: str, error: str):
        """Log job error"""
        try:
            job_info = self.active_jobs.get(job_id, {})
            
            log_entry = ScrapingLog(
                id=f"{job_id}_error",
                job_id=job_id,
                user_id=job_info.get('user_id', 'anonymous'),
                url=job_info.get('url', ''),
                status='error',
                error=error,
                created_at=datetime.utcnow()
            )
            
            session = self.Session()
            session.add(log_entry)
            session.commit()
            session.close()
            
            # Update error counts
            self.error_counts[error] += 1
            
            # Update Redis
            self.redis_client.hset(
                f"job:{job_id}",
                mapping={
                    'status': 'error',
                    'error': error,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )
            
            # Record error metric
            self._record_performance_metric('job_error', 1, {
                'job_id': job_id,
                'error_type': error[:50]  # Truncate long errors
            })
            
            # Clean up active jobs
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            
            logger.error(f"Job {job_id} failed: {error}")
            
        except Exception as e:
            logger.error(f"Failed to log job error: {str(e)}")
    
    def log_job_cancel(self, job_id: str):
        """Log job cancellation"""
        try:
            job_info = self.active_jobs.get(job_id, {})
            
            log_entry = ScrapingLog(
                id=f"{job_id}_cancel",
                job_id=job_id,
                user_id=job_info.get('user_id', 'anonymous'),
                url=job_info.get('url', ''),
                status='cancelled',
                created_at=datetime.utcnow()
            )
            
            session = self.Session()
            session.add(log_entry)
            session.commit()
            session.close()
            
            # Update Redis
            self.redis_client.hset(
                f"job:{job_id}",
                mapping={
                    'status': 'cancelled',
                    'timestamp': datetime.utcnow().isoformat()
                }
            )
            
            # Clean up active jobs
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            
            logger.info(f"Job {job_id} was cancelled")
            
        except Exception as e:
            logger.error(f"Failed to log job cancellation: {str(e)}")
    
    def _record_performance_metric(self, metric_name: str, value: float, tags: Dict[str, str]):
        """Record performance metric"""
        try:
            metric = PerformanceMetrics(
                id=f"{metric_name}_{int(time.time())}_{hash(str(tags))}",
                metric_name=metric_name,
                metric_value=value,
                tags=json.dumps(tags),
                timestamp=datetime.utcnow()
            )
            
            session = self.Session()
            session.add(metric)
            session.commit()
            session.close()
            
            # Store in Redis for real-time monitoring
            self.redis_client.lpush(
                f"metrics:{metric_name}",
                json.dumps({
                    'value': value,
                    'tags': tags,
                    'timestamp': datetime.utcnow().isoformat()
                })
            )
            
            # Keep only last 1000 metrics per type
            self.redis_client.ltrim(f"metrics:{metric_name}", 0, 999)
            
        except Exception as e:
            logger.error(f"Failed to record performance metric: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        try:
            session = self.Session()
            
            # Get job counts by status
            status_counts = session.query(
                ScrapingLog.status,
                func.count(ScrapingLog.id)
            ).group_by(ScrapingLog.status).all()
            
            # Get recent jobs (last 24 hours)
            since_yesterday = datetime.utcnow() - timedelta(days=1)
            recent_jobs = session.query(ScrapingLog).filter(
                ScrapingLog.created_at >= since_yesterday
            ).count()
            
            # Get average duration
            avg_duration = session.query(
                func.avg(ScrapingLog.duration)
            ).filter(
                ScrapingLog.duration.isnot(None)
            ).scalar()
            
            # Get error rate
            total_jobs = session.query(ScrapingLog).count()
            error_jobs = session.query(ScrapingLog).filter(
                ScrapingLog.status == 'error'
            ).count()
            
            error_rate = (error_jobs / total_jobs * 100) if total_jobs > 0 else 0
            
            session.close()
            
            return {
                'active_jobs': len(self.active_jobs),
                'total_jobs': total_jobs,
                'recent_jobs_24h': recent_jobs,
                'status_counts': dict(status_counts),
                'avg_duration': float(avg_duration) if avg_duration else 0,
                'error_rate': round(error_rate, 2),
                'top_errors': dict(sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
                'top_domains': dict(sorted(self.domain_counts.items(), key=lambda x: x[1], reverse=True)[:10])
            }
            
        except Exception as e:
            logger.error(f"Failed to get stats: {str(e)}")
            return {}
    
    def get_job_history(self, user_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get job history"""
        try:
            session = self.Session()
            
            query = session.query(ScrapingLog)
            if user_id:
                query = query.filter_by(user_id=user_id)
            
            jobs = query.order_by(ScrapingLog.created_at.desc()).limit(limit).all()
            
            session.close()
            
            return [
                {
                    'id': job.id,
                    'job_id': job.job_id,
                    'user_id': job.user_id,
                    'url': job.url,
                    'status': job.status,
                    'duration': job.duration,
                    'data_size': job.data_size,
                    'error': job.error,
                    'created_at': job.created_at.isoformat() if job.created_at else None
                }
                for job in jobs
            ]
            
        except Exception as e:
            logger.error(f"Failed to get job history: {str(e)}")
            return []
    
    def get_performance_metrics(self, metric_name: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Get performance metrics for a specific metric"""
        try:
            since_hours = datetime.utcnow() - timedelta(hours=hours)
            
            session = self.Session()
            metrics = session.query(PerformanceMetrics).filter(
                PerformanceMetrics.metric_name == metric_name,
                PerformanceMetrics.timestamp >= since_hours
            ).order_by(PerformanceMetrics.timestamp.desc()).all()
            session.close()
            
            return [
                {
                    'id': metric.id,
                    'metric_name': metric.metric_name,
                    'value': metric.metric_value,
                    'tags': json.loads(metric.tags) if metric.tags else {},
                    'timestamp': metric.timestamp.isoformat()
                }
                for metric in metrics
            ]
            
        except Exception as e:
            logger.error(f"Failed to get performance metrics: {str(e)}")
            return []
    
    def get_active_jobs(self) -> List[Dict[str, Any]]:
        """Get currently active jobs"""
        return [
            {
                'job_id': job_id,
                'url': info['url'],
                'user_id': info['user_id'],
                'start_time': info['start_time'].isoformat(),
                'duration': (datetime.utcnow() - info['start_time']).total_seconds()
            }
            for job_id, info in self.active_jobs.items()
        ]
    
    def cleanup_old_logs(self, days: int = 30):
        """Clean up old logs"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            session = self.Session()
            
            # Delete old scraping logs
            deleted_logs = session.query(ScrapingLog).filter(
                ScrapingLog.created_at < cutoff_date
            ).delete()
            
            # Delete old performance metrics
            deleted_metrics = session.query(PerformanceMetrics).filter(
                PerformanceMetrics.timestamp < cutoff_date
            ).delete()
            
            session.commit()
            session.close()
            
            logger.info(f"Cleaned up {deleted_logs} old logs and {deleted_metrics} old metrics")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {str(e)}")
    
    def export_logs(self, format: str = 'json', days: int = 7) -> str:
        """Export logs in specified format"""
        try:
            since_days = datetime.utcnow() - timedelta(days=days)
            
            session = self.Session()
            logs = session.query(ScrapingLog).filter(
                ScrapingLog.created_at >= since_days
            ).order_by(ScrapingLog.created_at.desc()).all()
            session.close()
            
            if format == 'json':
                return json.dumps([
                    {
                        'id': log.id,
                        'job_id': log.job_id,
                        'user_id': log.user_id,
                        'url': log.url,
                        'status': log.status,
                        'duration': log.duration,
                        'data_size': log.data_size,
                        'error': log.error,
                        'created_at': log.created_at.isoformat()
                    }
                    for log in logs
                ], indent=2)
            
            elif format == 'csv':
                import csv
                import io
                
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow(['ID', 'Job ID', 'User ID', 'URL', 'Status', 'Duration', 'Data Size', 'Error', 'Created At'])
                
                # Write rows
                for log in logs:
                    writer.writerow([
                        log.id,
                        log.job_id,
                        log.user_id,
                        log.url,
                        log.status,
                        log.duration or '',
                        log.data_size or '',
                        log.error or '',
                        log.created_at.isoformat()
                    ])
                
                return output.getvalue()
            
            else:
                raise ValueError(f"Unsupported format: {format}")
                
        except Exception as e:
            logger.error(f"Failed to export logs: {str(e)}")
            return ""
