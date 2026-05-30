"""
Database Integration for Storing Scraped Data
Supports both PostgreSQL and MongoDB
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

class DatabaseType(Enum):
    POSTGRESQL = "postgresql"
    MONGODB = "mongodb"

@dataclass
class ScrapedRecord:
    """Database record for scraped data."""
    id: Optional[str] = None
    job_id: str = ""
    url: str = ""
    timestamp: str = ""
    data: Dict[str, Any] = None
    screenshot_path: Optional[str] = None
    raw_html: Optional[str] = None
    extraction_time: float = 0.0
    created_at: Optional[datetime] = None

@dataclass
class JobRecord:
    """Database record for job information."""
    job_id: str = ""
    config: Dict[str, Any] = None
    status: str = ""
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    total_items: int = 0
    execution_time: float = 0.0

class DatabaseManager:
    """Database manager with support for PostgreSQL and MongoDB."""
    
    def __init__(self, db_type: DatabaseType = DatabaseType.POSTGRESQL, 
                 connection_string: str = None):
        self.db_type = db_type
        self.connection_string = connection_string or self._get_default_connection_string()
        self.client = None
        self._connect()
    
    def _get_default_connection_string(self) -> str:
        """Get default connection string based on database type."""
        if self.db_type == DatabaseType.POSTGRESQL:
            return "postgresql://user:password@localhost/scraper_db"
        elif self.db_type == DatabaseType.MONGODB:
            return "mongodb://localhost:27017/scraper_db"
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")
    
    def _connect(self):
        """Connect to the database."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                self._connect_postgresql()
            elif self.db_type == DatabaseType.MONGODB:
                self._connect_mongodb()
            
            logger.info(f"Connected to {self.db_type.value} database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _connect_postgresql(self):
        """Connect to PostgreSQL."""
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        self.client = psycopg2.connect(self.connection_string)
        self.client.cursor_factory = RealDictCursor
        
        # Create tables if they don't exist
        self._create_postgresql_tables()
    
    def _connect_mongodb(self):
        """Connect to MongoDB."""
        from pymongo import MongoClient
        
        self.client = MongoClient(self.connection_string)
        self.db = self.client.get_default_database()
        
        # Create indexes if they don't exist
        self._create_mongodb_indexes()
    
    def _create_postgresql_tables(self):
        """Create PostgreSQL tables."""
        cursor = self.client.cursor()
        
        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraping_jobs (
                job_id VARCHAR(255) PRIMARY KEY,
                config JSONB NOT NULL,
                status VARCHAR(50) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                started_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                result JSONB,
                error TEXT,
                total_items INTEGER DEFAULT 0,
                execution_time FLOAT DEFAULT 0.0
            )
        """)
        
        # Scraped data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scraped_data (
                id SERIAL PRIMARY KEY,
                job_id VARCHAR(255) NOT NULL REFERENCES scraping_jobs(job_id),
                url TEXT NOT NULL,
                timestamp VARCHAR(255) NOT NULL,
                data JSONB NOT NULL,
                screenshot_path TEXT,
                raw_html TEXT,
                extraction_time FLOAT DEFAULT 0.0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraped_data_job_id ON scraped_data(job_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraped_data_url ON scraped_data(url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraping_jobs_status ON scraping_jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraping_jobs_created_at ON scraping_jobs(created_at)")
        
        self.client.commit()
        cursor.close()
    
    def _create_mongodb_indexes(self):
        """Create MongoDB indexes."""
        # Jobs collection indexes
        self.db.scraping_jobs.create_index("job_id", unique=True)
        self.db.scraping_jobs.create_index("status")
        self.db.scraping_jobs.create_index("created_at")
        
        # Scraped data collection indexes
        self.db.scraped_data.create_index("job_id")
        self.db.scraped_data.create_index("url")
        self.db.scraped_data.create_index("created_at")
    
    def save_job(self, job_record: JobRecord) -> bool:
        """Save job record to database."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._save_job_postgresql(job_record)
            elif self.db_type == DatabaseType.MONGODB:
                return self._save_job_mongodb(job_record)
        except Exception as e:
            logger.error(f"Failed to save job: {e}")
            return False
    
    def _save_job_postgresql(self, job_record: JobRecord) -> bool:
        """Save job to PostgreSQL."""
        cursor = self.client.cursor()
        
        cursor.execute("""
            INSERT INTO scraping_jobs 
            (job_id, config, status, created_at, started_at, completed_at, result, error, total_items, execution_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id) DO UPDATE SET
                config = EXCLUDED.config,
                status = EXCLUDED.status,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                result = EXCLUDED.result,
                error = EXCLUDED.error,
                total_items = EXCLUDED.total_items,
                execution_time = EXCLUDED.execution_time
        """, (
            job_record.job_id,
            json.dumps(job_record.config) if job_record.config else {},
            job_record.status,
            job_record.created_at,
            job_record.started_at,
            job_record.completed_at,
            json.dumps(job_record.result) if job_record.result else None,
            job_record.error,
            job_record.total_items,
            job_record.execution_time
        ))
        
        self.client.commit()
        cursor.close()
        return True
    
    def _save_job_mongodb(self, job_record: JobRecord) -> bool:
        """Save job to MongoDB."""
        doc = asdict(job_record)
        doc.pop('id', None)  # Remove id field
        
        self.db.scraping_jobs.replace_one(
            {"job_id": job_record.job_id},
            doc,
            upsert=True
        )
        return True
    
    def save_scraped_data(self, records: List[ScrapedRecord]) -> bool:
        """Save scraped data records to database."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._save_scraped_data_postgresql(records)
            elif self.db_type == DatabaseType.MONGODB:
                return self._save_scraped_data_mongodb(records)
        except Exception as e:
            logger.error(f"Failed to save scraped data: {e}")
            return False
    
    def _save_scraped_data_postgresql(self, records: List[ScrapedRecord]) -> bool:
        """Save scraped data to PostgreSQL."""
        cursor = self.client.cursor()
        
        for record in records:
            cursor.execute("""
                INSERT INTO scraped_data 
                (job_id, url, timestamp, data, screenshot_path, raw_html, extraction_time, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record.job_id,
                record.url,
                record.timestamp,
                json.dumps(record.data) if record.data else {},
                record.screenshot_path,
                record.raw_html,
                record.extraction_time,
                record.created_at or datetime.utcnow()
            ))
        
        self.client.commit()
        cursor.close()
        return True
    
    def _save_scraped_data_mongodb(self, records: List[ScrapedRecord]) -> bool:
        """Save scraped data to MongoDB."""
        docs = []
        for record in records:
            doc = asdict(record)
            doc.pop('id', None)  # Remove id field
            docs.append(doc)
        
        if docs:
            self.db.scraped_data.insert_many(docs)
        return True
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get job record by ID."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._get_job_postgresql(job_id)
            elif self.db_type == DatabaseType.MONGODB:
                return self._get_job_mongodb(job_id)
        except Exception as e:
            logger.error(f"Failed to get job: {e}")
            return None
    
    def _get_job_postgresql(self, job_id: str) -> Optional[JobRecord]:
        """Get job from PostgreSQL."""
        cursor = self.client.cursor()
        
        cursor.execute("SELECT * FROM scraping_jobs WHERE job_id = %s", (job_id,))
        row = cursor.fetchone()
        cursor.close()
        
        if row:
            return JobRecord(
                job_id=row['job_id'],
                config=row['config'],
                status=row['status'],
                created_at=row['created_at'],
                started_at=row['started_at'],
                completed_at=row['completed_at'],
                result=row['result'],
                error=row['error'],
                total_items=row['total_items'],
                execution_time=row['execution_time']
            )
        return None
    
    def _get_job_mongodb(self, job_id: str) -> Optional[JobRecord]:
        """Get job from MongoDB."""
        doc = self.db.scraping_jobs.find_one({"job_id": job_id})
        
        if doc:
            doc.pop('_id', None)  # Remove MongoDB _id
            return JobRecord(**doc)
        return None
    
    def get_scraped_data(self, job_id: str, limit: int = 100) -> List[ScrapedRecord]:
        """Get scraped data for a job."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._get_scraped_data_postgresql(job_id, limit)
            elif self.db_type == DatabaseType.MONGODB:
                return self._get_scraped_data_mongodb(job_id, limit)
        except Exception as e:
            logger.error(f"Failed to get scraped data: {e}")
            return []
    
    def _get_scraped_data_postgresql(self, job_id: str, limit: int) -> List[ScrapedRecord]:
        """Get scraped data from PostgreSQL."""
        cursor = self.client.cursor()
        
        cursor.execute("""
            SELECT * FROM scraped_data 
            WHERE job_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s
        """, (job_id, limit))
        
        records = []
        for row in cursor.fetchall():
            records.append(ScrapedRecord(
                id=str(row['id']),
                job_id=row['job_id'],
                url=row['url'],
                timestamp=row['timestamp'],
                data=row['data'],
                screenshot_path=row['screenshot_path'],
                raw_html=row['raw_html'],
                extraction_time=row['extraction_time'],
                created_at=row['created_at']
            ))
        
        cursor.close()
        return records
    
    def _get_scraped_data_mongodb(self, job_id: str, limit: int) -> List[ScrapedRecord]:
        """Get scraped data from MongoDB."""
        docs = self.db.scraped_data.find(
            {"job_id": job_id}
        ).sort("created_at", -1).limit(limit)
        
        records = []
        for doc in docs:
            doc.pop('_id', None)  # Remove MongoDB _id
            records.append(ScrapedRecord(**doc))
        
        return records
    
    def list_jobs(self, status: Optional[str] = None, limit: int = 50) -> List[JobRecord]:
        """List jobs with optional status filter."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._list_jobs_postgresql(status, limit)
            elif self.db_type == DatabaseType.MONGODB:
                return self._list_jobs_mongodb(status, limit)
        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []
    
    def _list_jobs_postgresql(self, status: Optional[str], limit: int) -> List[JobRecord]:
        """List jobs from PostgreSQL."""
        cursor = self.client.cursor()
        
        if status:
            cursor.execute("""
                SELECT * FROM scraping_jobs 
                WHERE status = %s 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (status, limit))
        else:
            cursor.execute("""
                SELECT * FROM scraping_jobs 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
        
        jobs = []
        for row in cursor.fetchall():
            jobs.append(JobRecord(
                job_id=row['job_id'],
                config=row['config'],
                status=row['status'],
                created_at=row['created_at'],
                started_at=row['started_at'],
                completed_at=row['completed_at'],
                result=row['result'],
                error=row['error'],
                total_items=row['total_items'],
                execution_time=row['execution_time']
            ))
        
        cursor.close()
        return jobs
    
    def _list_jobs_mongodb(self, status: Optional[str], limit: int) -> List[JobRecord]:
        """List jobs from MongoDB."""
        query = {"status": status} if status else {}
        
        docs = self.db.scraping_jobs.find(query).sort("created_at", -1).limit(limit)
        
        jobs = []
        for doc in docs:
            doc.pop('_id', None)  # Remove MongoDB _id
            jobs.append(JobRecord(**doc))
        
        return jobs
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._get_statistics_postgresql()
            elif self.db_type == DatabaseType.MONGODB:
                return self._get_statistics_mongodb()
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def _get_statistics_postgresql(self) -> Dict[str, Any]:
        """Get statistics from PostgreSQL."""
        cursor = self.client.cursor()
        
        # Job statistics
        cursor.execute("SELECT status, COUNT(*) FROM scraping_jobs GROUP BY status")
        job_stats = dict(cursor.fetchall())
        
        # Total records
        cursor.execute("SELECT COUNT(*) FROM scraped_data")
        total_records = cursor.fetchone()[0]
        
        # Recent activity
        cursor.execute("""
            SELECT COUNT(*) FROM scraping_jobs 
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """)
        recent_jobs = cursor.fetchone()[0]
        
        cursor.close()
        
        return {
            'total_jobs': sum(job_stats.values()),
            'jobs_by_status': job_stats,
            'total_records': total_records,
            'recent_jobs_24h': recent_jobs
        }
    
    def _get_statistics_mongodb(self) -> Dict[str, Any]:
        """Get statistics from MongoDB."""
        # Job statistics
        job_pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$group": {"_id": None, "total": {"$sum": "$count"}, "statuses": {"$push": {"k": "$_id", "v": "$count"}}}}
        ]
        
        job_result = list(self.db.scraping_jobs.aggregate(job_pipeline))
        job_stats = {}
        total_jobs = 0
        
        if job_result:
            total_jobs = job_result[0]["total"]
            for status in job_result[0]["statuses"]:
                job_stats[status["k"]] = status["v"]
        
        # Total records
        total_records = self.db.scraped_data.count_documents({})
        
        # Recent activity
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_jobs = self.db.scraping_jobs.count_documents({
            "created_at": {"$gte": recent_cutoff}
        })
        
        return {
            'total_jobs': total_jobs,
            'jobs_by_status': job_stats,
            'total_records': total_records,
            'recent_jobs_24h': recent_jobs
        }
    
    def delete_job(self, job_id: str) -> bool:
        """Delete job and associated data."""
        try:
            if self.db_type == DatabaseType.POSTGRESQL:
                return self._delete_job_postgresql(job_id)
            elif self.db_type == DatabaseType.MONGODB:
                return self._delete_job_mongodb(job_id)
        except Exception as e:
            logger.error(f"Failed to delete job: {e}")
            return False
    
    def _delete_job_postgresql(self, job_id: str) -> bool:
        """Delete job from PostgreSQL."""
        cursor = self.client.cursor()
        
        # Delete scraped data first (foreign key constraint)
        cursor.execute("DELETE FROM scraped_data WHERE job_id = %s", (job_id,))
        
        # Delete job
        cursor.execute("DELETE FROM scraping_jobs WHERE job_id = %s", (job_id,))
        
        self.client.commit()
        cursor.close()
        return True
    
    def _delete_job_mongodb(self, job_id: str) -> bool:
        """Delete job from MongoDB."""
        # Delete scraped data
        self.db.scraped_data.delete_many({"job_id": job_id})
        
        # Delete job
        self.db.scraping_jobs.delete_one({"job_id": job_id})
        
        return True
    
    def close(self):
        """Close database connection."""
        if self.client:
            if self.db_type == DatabaseType.POSTGRESQL:
                self.client.close()
            elif self.db_type == DatabaseType.MONGODB:
                self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
