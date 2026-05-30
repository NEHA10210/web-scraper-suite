"""
Data Scraper Blueprint - Complete implementation with SQLite and Playwright
"""

import logging
import json
import requests
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, request, session, jsonify, send_file
from werkzeug.exceptions import BadRequest

from responses import bad_request, server_error, success
from auth import login_required
from models import db, ActivityLog

logger = logging.getLogger(__name__)

data_scraper_bp = Blueprint("data_scraper", __name__)

# ── Helper Functions ────────────────────────────────────────────────────────

def scrape_website(url, scrape_type, use_playwright):
    """Complete scraping function with Playwright support."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    start_time = time.time()
    
    try:
        # Use Playwright for JS-heavy sites
        if use_playwright:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(headers)
                page.goto(url, wait_until='networkidle', timeout=30000)
                page.wait_for_timeout(2000)
                html_content = page.content()
                browser.close()
        else:
            response = requests.get(url, headers=headers, timeout=30)
            html_content = response.text
        
        soup = BeautifulSoup(html_content, 'lxml')
        duration = round((time.time() - start_time) * 1000)
        
        results = {
            'success': True,
            'url': url,
            'duration_ms': duration,
            'data': {}
        }
        
        # Remove scripts and styles for clean text
        for tag in soup(['script','style','nav','footer','header']):
            tag.decompose()
        
        if scrape_type == 'text' or scrape_type == 'all':
            # Extract headings
            headings = []
            for level in ['h1','h2','h3','h4']:
                for tag in soup.find_all(level):
                    text = tag.get_text(strip=True)
                    if text and len(text) > 2:
                        headings.append({
                            'level': level.upper(),
                            'text': text
                        })
            
            # Extract paragraphs
            skip_phrases = [
                'skip to', 'skip navigation', 
                'jump to', 'go to main',
                'start of', 'end of',
                'opens in a new tab',
                'opens in a new window',
                'back to top'
            ]
            
            paragraphs = []
            for p in soup.find_all('p'):
                text = p.get_text(strip=True)
                if any(phrase in text.lower() for phrase in skip_phrases):
                    continue
                if text and len(text) > 20:
                    paragraphs.append(text)
            
            # Extract full clean text
            full_text = soup.get_text(separator='\n', strip=True)
            # Clean up blank lines and filter noise
            noise_lines = [
                'loading finished',
                'loading...',
                'please wait',
                'page loading',
                'dom content loaded',
                'network idle',
            ]
            lines = [
                l.strip() for l in full_text.splitlines()
                if l.strip() 
                and len(l.strip()) > 2
                and not any(
                    noise in l.strip().lower() 
                    for noise in noise_lines
                )
                and not any(
                    phrase in l.strip().lower() 
                    for phrase in skip_phrases
                )
            ]
            clean_text = '\n'.join(lines[:200])
            
            # Apply Unicode cleaning to full text
            def clean_unicode(text):
                # Remove invisible Unicode characters
                text = text.replace('\u2060', '')  # word joiner ⁠
                text = text.replace('\u200b', '')  # zero width space
                text = text.replace('\ufeff', '')  # BOM
                text = text.replace('\u00ad', '')  # soft hyphen
                # Clean up multiple blank lines that result
                import re
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = re.sub(r' {2,}', ' ', text)
                return text.strip()
            
            clean_text = clean_unicode(clean_text)
            
            results['data']['headings'] = headings[:20]
            results['data']['paragraphs'] = paragraphs[:20]
            results['data']['full_text'] = clean_text
            results['data']['word_count'] = len(full_text.split())
        
        if scrape_type == 'links' or scrape_type == 'all':
            import unicodedata
            
            def clean_link_text(text):
                # Remove invisible/special Unicode characters
                # U+2060 word joiner, U+200B zero-width space,
                # U+FEFF BOM, U+00AD soft hyphen etc.
                text = ''.join(
                    c for c in text 
                    if not unicodedata.category(c).startswith('C')
                    or c in ['\n', '\t', ' ']
                )
                # Remove the specific ⁠ character (U+2060)
                text = text.replace('\u2060', '')
                text = text.replace('\u200b', '')
                text = text.replace('\ufeff', '')
                text = text.replace('\u00ad', '')
                # Clean extra whitespace
                text = re.sub(r'\s+', ' ', text).strip()
                return text
            
            links = []
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                text = a.get_text(strip=True)
                
                # Apply Unicode cleaning
                text = clean_link_text(text)
                
                # Remove accessibility noise
                text = re.sub(
                    r'\(opens in a new tab.*?\)', '', text, 
                    flags=re.IGNORECASE).strip()
                text = re.sub(
                    r'\(opens a new window.*?\)', '', text,
                    flags=re.IGNORECASE).strip()
                text = re.sub(
                    r'\s+', ' ', text).strip()
                
                # Replace generic text with URL-based name
                if text.lower() in ['here', 'click', 'this', 'link', 'more']:
                    from urllib.parse import urlparse
                    path = urlparse(href).path
                    path_text = path.strip('/').split('/')[-1]
                    path_text = path_text.replace('-', ' ').replace('_', ' ')
                    if path_text:
                        text = path_text.title()
                        # "contact-sales" becomes "Contact Sales"
                
                # Skip if text is empty after cleaning
                if not text or len(text) < 2:
                    continue
                
                if href.startswith('http') and text:
                    links.append({
                        'text': text[:80],
                        'url': href
                    })
            
            # Remove duplicates based on URL
            seen_urls = set()
            unique_links = []
            for link in links:
                if link['url'] not in seen_urls:
                    seen_urls.add(link['url'])
                    unique_links.append(link)
            links = unique_links
            
            # Filter out useless links (only if we have better ones)
            skip_texts = ['learn more', 'click here', 'here', 'read more', 'more', 'link', '']
            if len(links) > 5:  # Only filter if we have enough links
                filtered_links = []
                for link in links:
                    if link['text'].lower() not in skip_texts:
                        filtered_links.append(link)
                if filtered_links:  # Keep filtered if not empty
                    links = filtered_links
            
            results['data']['links'] = links[:50]
            results['data']['links_count'] = len(links)
        
        if scrape_type == 'images' or scrape_type == 'all':
            images = []
            for img in soup.find_all('img'):
                src = img.get('src','')
                alt = img.get('alt','No alt text')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        base = urlparse(url)
                        src = f"{base.scheme}://{base.netloc}{src}"
                    images.append({
                        'src': src,
                        'alt': alt
                    })
            results['data']['images'] = images[:30]
            results['data']['images_count'] = len(images)
        
        if scrape_type == 'emails':
            full_text = soup.get_text()
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails = list(set(re.findall(email_pattern, full_text)))
            results['data']['emails'] = emails
            results['data']['emails_count'] = len(emails)
        
        if scrape_type == 'meta':
            meta_data = {}
            title = soup.find('title')
            meta_data['title'] = title.get_text(strip=True) if title else ''
            
            for meta in soup.find_all('meta'):
                name = meta.get('name') or meta.get('property','')
                content = meta.get('content','')
                if name and content:
                    meta_data[name] = content
            
            results['data']['meta'] = meta_data
            results['records_found'] = len(results['data'].get('meta', {}))
        
        # Count total records
        total = 0
        for key, val in results['data'].items():
            if isinstance(val, list):
                total += len(val)
        results['records_found'] = total
        
        return results
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'url': url
        }

def format_time_ago(dt):
    """Format datetime as 'X time ago'."""
    if not dt:
        return "Never"
    
    now = datetime.utcnow()
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return "Just now"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} min{'s' if minutes > 1 else ''} ago"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff < timedelta(days=7):
        days = diff.days
        return f"{days} day{'s' if days > 1 else ''} ago"
    else:
        return dt.strftime('%Y-%m-%d')

# ── Page Routes ────────────────────────────────────────────────────────────────

@data_scraper_bp.route("/data-scraper")
@login_required
def page():
    return render_template("data_scraper_admin.html", active_page='data_scraper')

# ── API Routes ─────────────────────────────────────────────────────────────────--

@data_scraper_bp.route("/data-scraper/scrape", methods=["POST"])
@login_required
def scrape():
    """Run scraping on the given URL."""
    try:
        # Get data from request
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()
        
        url = data.get('url', '').strip()
        scrape_type = data.get('scrape_type', 'text')
        use_playwright = data.get('use_playwright', False)
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 200
            
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        print(f"Scraping URL: {url}, type: {scrape_type}, playwright: {use_playwright}")
        
        # Test if URL is reachable first
        try:
            import requests as req
            test = req.head(url, timeout=10, allow_redirects=True)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Cannot reach website: {str(e)}'
            }), 200
        
        # Run scraping
        result = scrape_website(url, scrape_type, use_playwright)
        
        if not result.get('success'):
            # Save failed job
            save_job_to_db(url, scrape_type, use_playwright, 'failed', 0, result.get('error'))
            return jsonify(result)
        
        # Save successful job
        job_id = save_job_to_db(url, scrape_type, use_playwright, 'completed', 
                               result.get('records_found', 0), None)
        
        # Log activity
        try:
            activity = ActivityLog(
                user_id=session.get('user_id'),
                event_type='scrape',
                title='Data scraping completed',
                subtitle=f"{url} ({result.get('records_found', 0)} records)"
            )
            db.session.add(activity)
            db.session.commit()
        except:
            pass  # Ignore activity log errors
        
        result['job_id'] = job_id
        print(f"Scraping completed for {url}, found {result.get('records_found')} records")
        return jsonify(result)
        
    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")
        logger.exception("Scraping failed")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 200  # Never return 500

def save_job_to_db(url, scrape_type, use_playwright, status, records_found, error_message):
    """Save scraping job to database."""
    try:
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO scrape_jobs 
            (user_id, url, scrape_type, use_playwright, status, 
             records_found, error_message, created_at, completed_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        ''', (
            session.get('user_id', 1),
            url,
            scrape_type,
            1 if use_playwright else 0,
            status,
            records_found,
            error_message,
            datetime.now().isoformat(),
            datetime.now().isoformat() if status == 'completed' else None
        ))
        
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return job_id
        
    except Exception as e:
        print(f"Save job error: {str(e)}")
        return None

@data_scraper_bp.route("/data-scraper/jobs")
@login_required
def get_scrape_jobs():
    """Get user's scraping jobs history."""
    try:
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, url, scrape_type, status, 
                   records_found, created_at
            FROM scrape_jobs 
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 10
        ''', (session.get('user_id', 1),))
        
        rows = cursor.fetchall()
        conn.close()
        
        jobs = []
        for r in rows:
            created = datetime.fromisoformat(r[5])
            diff = datetime.now() - created
            if diff.seconds < 60:
                ago = 'Just now'
            elif diff.seconds < 3600:
                ago = f"{diff.seconds//60}m ago"
            else:
                ago = f"{diff.seconds//3600}h ago"
            
            jobs.append({
                'id': r[0], 
                'url': r[1],
                'scrape_type': r[2], 
                'status': r[3],
                'records_found': r[4], 
                'time_ago': ago
            })
        
        return jsonify(jobs)
        
    except Exception as e:
        print(f"Jobs load error: {str(e)}")
        logger.exception("Failed to load jobs")
        return jsonify([])

@data_scraper_bp.route("/data-scraper/export/<int:job_id>")
@login_required
def export_job(job_id):
    """Export scraped data as JSON file."""
    try:
        import sqlite3
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT url, scrape_type, status, records_found, created_at
            FROM scrape_jobs 
            WHERE id = ? AND user_id = ?
        ''', (job_id, session.get('user_id', 1)))
        
        job = cursor.fetchone()
        conn.close()
        
        if not job:
            return jsonify({"success": False, "error": "Job not found"}), 404
        
        # For now, return job info as JSON
        # In a real implementation, you'd fetch the actual scraped data
        export_data = {
            'job_id': job_id,
            'url': job[0],
            'scrape_type': job[1],
            'status': job[2],
            'records_found': job[3],
            'created_at': job[4],
            'exported_at': datetime.now().isoformat()
        }
        
        # Create JSON file
        json_str = json.dumps(export_data, indent=2)
        
        # Return as downloadable file
        from io import BytesIO
        output = BytesIO()
        output.write(json_str.encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f'scrape_job_{job_id}.json',
            mimetype='application/json'
        )
        
    except Exception as e:
        print(f"Export error: {str(e)}")
        logger.exception("Failed to export job")
        return jsonify({"success": False, "error": "Export failed"}), 500
