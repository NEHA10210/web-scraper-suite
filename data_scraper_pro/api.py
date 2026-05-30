"""
Enhanced API endpoints for the professional Data Scraper
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import asyncio
import os

from .scraper_engine import AdvancedScraper, ScrapingConfig, ExportFormat, ScrapingStatus
from .tasks import scrape_website_task, get_job_status, cancel_job
from .templates import TemplateManager, ScrapingTemplate
from .auth_handler import AuthHandler, LoginCredentials, PREDEFINED_LOGINS
from .monitoring import MonitoringManager

logger = logging.getLogger(__name__)

class DataScraperAPI:
    def __init__(self, app: Flask = None):
        self.app = app
        self.scraper = AdvancedScraper()
        self.template_manager = TemplateManager()
        self.auth_handler = AuthHandler()
        self.monitoring = MonitoringManager()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        """Initialize Flask app with API routes"""
        self.app = app
        CORS(app)
        
        # Register routes
        self._register_routes()
        
        # Rate limiting
        self._setup_rate_limiting()
        
        # Security
        self._setup_security()
    
    def _register_routes(self):
        """Register all API routes"""
        
        @self.app.route('/api/v1/scraper/templates', methods=['GET'])
        def get_templates():
            """Get available scraping templates"""
            try:
                category = request.args.get('category')
                templates = self.template_manager.list_templates(category)
                
                return jsonify({
                    'success': True,
                    'templates': [
                        {
                            'name': t.name,
                            'description': t.description,
                            'category': t.category,
                            'selectors': t.selectors,
                            'wait_for': t.wait_for,
                            'scroll': t.scroll,
                            'pagination': t.pagination
                        }
                        for t in templates
                    ]
                })
            except Exception as e:
                logger.error(f"Error getting templates: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/templates/<name>', methods=['GET'])
        def get_template(name):
            """Get specific template"""
            try:
                template = self.template_manager.get_template(name)
                if not template:
                    return jsonify({'success': False, 'error': 'Template not found'}), 404
                
                return jsonify({
                    'success': True,
                    'template': {
                        'name': template.name,
                        'description': template.description,
                        'category': template.category,
                        'selectors': template.selectors,
                        'wait_for': template.wait_for,
                        'scroll': template.scroll,
                        'pagination': template.pagination,
                        'custom_config': template.custom_config
                    }
                })
            except Exception as e:
                logger.error(f"Error getting template: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/scrape', methods=['POST'])
        def start_scraping():
            """Start a new scraping job"""
            try:
                data = request.get_json()
                
                # Validate required fields
                if not data.get('url'):
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                # Create job ID
                job_id = str(uuid.uuid4())
                
                # Build configuration
                config_dict = {
                    'url': data['url'],
                    'selectors': data.get('selectors'),
                    'wait_for': data.get('wait_for'),
                    'scroll': data.get('scroll', False),
                    'screenshots': data.get('screenshots', False),
                    'javascript': data.get('javascript', True),
                    'timeout': data.get('timeout', 30000),
                    'retry_count': data.get('retry_count', 3),
                    'delay': data.get('delay', 1.0),
                    'user_agent': data.get('user_agent'),
                    'proxy': data.get('proxy'),
                    'export_format': ExportFormat(data.get('export_format', 'json')),
                    'save_to_db': data.get('save_to_db', False)
                }
                
                # Handle template
                if data.get('template'):
                    template = self.template_manager.get_template(data['template'])
                    if template:
                        config_dict['selectors'] = template.selectors
                        config_dict['wait_for'] = template.wait_for
                        config_dict['scroll'] = template.scroll
                
                # Handle authentication
                if data.get('auth'):
                    auth_data = data['auth']
                    if auth_data.get('type') == 'login':
                        # Add login credentials to config
                        config_dict['auth'] = auth_data
                
                # Create job record
                self._create_job_record(job_id, data)
                
                # Start async task
                task = scrape_website_task.delay(job_id, config_dict)
                
                # Log monitoring
                self.monitoring.log_job_start(job_id, data)
                
                return jsonify({
                    'success': True,
                    'job_id': job_id,
                    'task_id': task.id,
                    'status': 'started'
                })
                
            except Exception as e:
                logger.error(f"Error starting scraping: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/scrape/sync', methods=['POST'])
        def scrape_sync():
            """Synchronous scraping (for small jobs)"""
            try:
                data = request.get_json()
                
                if not data.get('url'):
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                # Create configuration
                config = ScrapingConfig(
                    url=data['url'],
                    selectors=data.get('selectors'),
                    wait_for=data.get('wait_for'),
                    scroll=data.get('scroll', False),
                    screenshots=data.get('screenshots', False),
                    javascript=data.get('javascript', True),
                    timeout=data.get('timeout', 30000),
                    retry_count=data.get('retry_count', 3),
                    delay=data.get('delay', 1.0),
                    user_agent=data.get('user_agent'),
                    proxy=data.get('proxy'),
                    export_format=ExportFormat(data.get('export_format', 'json')),
                    save_to_db=data.get('save_to_db', False)
                )
                
                # Run scraping synchronously
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.scraper.scrape(config))
                loop.close()
                
                # Export data
                exported_data = self.scraper.export_data(result, config.export_format)
                
                return jsonify({
                    'success': True,
                    'data': result,
                    'exported': exported_data,
                    'format': config.export_format.value
                })
                
            except Exception as e:
                logger.error(f"Error in sync scraping: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/jobs/<job_id>', methods=['GET'])
        def get_job(job_id):
            """Get job status and results"""
            try:
                job_info = get_job_status(job_id)
                
                if 'error' in job_info:
                    return jsonify({'success': False, 'error': job_info['error']}), 404
                
                return jsonify({
                    'success': True,
                    'job': job_info
                })
                
            except Exception as e:
                logger.error(f"Error getting job: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/jobs/<job_id>/cancel', methods=['POST'])
        def cancel_job_endpoint(job_id):
            """Cancel a running job"""
            try:
                success = cancel_job(job_id)
                
                if success:
                    self.monitoring.log_job_cancel(job_id)
                    return jsonify({'success': True, 'message': 'Job cancelled'})
                else:
                    return jsonify({'success': False, 'error': 'Failed to cancel job'}), 400
                    
            except Exception as e:
                logger.error(f"Error cancelling job: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/jobs', methods=['GET'])
        def list_jobs():
            """List user's jobs"""
            try:
                user_id = request.args.get('user_id', 'anonymous')
                status = request.args.get('status')
                limit = int(request.args.get('limit', 50))
                offset = int(request.args.get('offset', 0))
                
                jobs = self._get_user_jobs(user_id, status, limit, offset)
                
                return jsonify({
                    'success': True,
                    'jobs': jobs,
                    'total': len(jobs)
                })
                
            except Exception as e:
                logger.error(f"Error listing jobs: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/jobs/<job_id>/download', methods=['GET'])
        def download_job_result(job_id):
            """Download job result as file"""
            try:
                format_type = request.args.get('format', 'json')
                job_info = get_job_status(job_id)
                
                if 'error' in job_info:
                    return jsonify({'success': False, 'error': job_info['error']}), 404
                
                if not job_info.get('result'):
                    return jsonify({'success': False, 'error': 'No result available'}), 400
                
                result_data = job_info['result']
                
                if format_type == 'json':
                    filename = f"scraped_data_{job_id}.json"
                    content = json.dumps(result_data['data'], indent=2, ensure_ascii=False)
                    mimetype = 'application/json'
                elif format_type == 'csv':
                    filename = f"scraped_data_{job_id}.csv"
                    content = result_data['exported']
                    mimetype = 'text/csv'
                else:
                    return jsonify({'success': False, 'error': 'Invalid format'}), 400
                
                # Create temporary file
                temp_file = os.path.join('/tmp', filename)
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                return send_file(temp_file, as_attachment=True, download_name=filename, mimetype=mimetype)
                
            except Exception as e:
                logger.error(f"Error downloading result: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/auth/test', methods=['POST'])
        def test_auth():
            """Test authentication credentials"""
            try:
                data = request.get_json()
                
                if not data.get('login_url') or not data.get('username') or not data.get('password'):
                    return jsonify({'success': False, 'error': 'Missing required auth fields'}), 400
                
                credentials = LoginCredentials(
                    username=data['username'],
                    password=data['password'],
                    login_url=data['login_url'],
                    username_selector=data.get('username_selector', 'input[name="username"], input[type="text"]'),
                    password_selector=data.get('password_selector', 'input[name="password"], input[type="password"]'),
                    submit_selector=data.get('submit_selector', 'button[type="submit"], input[type="submit"]'),
                    success_indicator=data.get('success_indicator')
                )
                
                # Test login
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.auth_handler.test_login(credentials))
                loop.close()
                
                return jsonify({
                    'success': True,
                    'result': result
                })
                
            except Exception as e:
                logger.error(f"Error testing auth: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/templates', methods=['POST'])
        def create_template():
            """Create custom template"""
            try:
                data = request.get_json()
                
                template = ScrapingTemplate(
                    name=data['name'],
                    description=data.get('description', ''),
                    category=data.get('category', 'custom'),
                    selectors=data['selectors'],
                    wait_for=data.get('wait_for'),
                    scroll=data.get('scroll', False),
                    pagination=data.get('pagination'),
                    custom_config=data.get('custom_config')
                )
                
                # Validate template
                from .templates import validate_template
                errors = validate_template(template)
                if errors:
                    return jsonify({'success': False, 'error': 'Validation failed', 'details': errors}), 400
                
                # Save template
                success = self.template_manager.save_template(template)
                
                if success:
                    return jsonify({
                        'success': True,
                        'message': 'Template created successfully',
                        'template': {
                            'name': template.name,
                            'description': template.description,
                            'category': template.category
                        }
                    })
                else:
                    return jsonify({'success': False, 'error': 'Failed to save template'}), 500
                    
            except Exception as e:
                logger.error(f"Error creating template: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/monitoring/stats', methods=['GET'])
        def get_monitoring_stats():
            """Get monitoring statistics"""
            try:
                stats = self.monitoring.get_stats()
                return jsonify({
                    'success': True,
                    'stats': stats
                })
            except Exception as e:
                logger.error(f"Error getting stats: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
        
        @self.app.route('/api/v1/scraper/validate-url', methods=['POST'])
        def validate_url():
            """Validate URL for scraping"""
            try:
                data = request.get_json()
                url = data.get('url')
                
                if not url:
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                is_valid = self.scraper.validate_url(url)
                
                return jsonify({
                    'success': True,
                    'valid': is_valid,
                    'message': 'URL is valid for scraping' if is_valid else 'URL is invalid or blocked'
                })
                
            except Exception as e:
                logger.error(f"Error validating URL: {str(e)}")
                return jsonify({'success': False, 'error': str(e)}), 500
    
    def _setup_rate_limiting(self):
        """Setup rate limiting"""
        # Implementation for rate limiting
        pass
    
    def _setup_security(self):
        """Setup security measures"""
        # Implementation for security
        pass
    
    def _create_job_record(self, job_id: str, data: Dict[str, Any]):
        """Create job record in database"""
        from .scraper_engine import ScrapingJob, Session
        
        session = Session()
        try:
            job = ScrapingJob(
                id=job_id,
                url=data['url'],
                status=ScrapingStatus.PENDING.value,
                config=json.dumps(data),
                user_id=data.get('user_id', 'anonymous')
            )
            session.add(job)
            session.commit()
        finally:
            session.close()
    
    def _get_user_jobs(self, user_id: str, status: Optional[str], limit: int, offset: int) -> List[Dict[str, Any]]:
        """Get user's jobs from database"""
        from .scraper_engine import ScrapingJob, Session
        
        session = Session()
        try:
            query = session.query(ScrapingJob).filter_by(user_id=user_id)
            
            if status:
                query = query.filter_by(status=status)
            
            jobs = query.order_by(ScrapingJob.created_at.desc()).offset(offset).limit(limit).all()
            
            return [
                {
                    'id': job.id,
                    'url': job.url,
                    'status': job.status,
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                    'started_at': job.started_at.isoformat() if job.started_at else None,
                    'completed_at': job.completed_at.isoformat() if job.completed_at else None,
                    'retry_count': job.retry_count
                }
                for job in jobs
            ]
        finally:
            session.close()
