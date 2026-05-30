"""
SEO Analyzer Blueprint - Complete implementation with SQLite and Playwright support
"""

import logging
import json
import requests
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, request, session, jsonify
from werkzeug.exceptions import BadRequest

from responses import bad_request, server_error, success
from auth import login_required
from models import db, SEOAnalysis, ActivityLog

logger = logging.getLogger(__name__)

seo_analyzer_bp = Blueprint("seo_analyzer", __name__)

# ── Helper Functions ────────────────────────────────────────────────────────

def scrape_with_playwright(url):
    """Scrape URL using Playwright for JS-heavy sites."""
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            content = page.content()
            browser.close()
            return content
    except Exception as e:
        print(f"Playwright failed: {e}")
        return None

def analyze_seo(url):
    """Comprehensive SEO analysis function with improved error handling."""
    print(f"Analyzing URL: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    start_time = time.time()
    
    # First try with requests with better error handling
    try:
        response = requests.get(
            url, 
            headers=headers, 
            timeout=30,  # increase timeout
            allow_redirects=True
        )
        load_time = int((time.time() - start_time) * 1000)
        
        if response.status_code != 200:
            return {
                "success": False, 
                "error": f"Website returned {response.status_code}"
            }
        
        # Limit content size for large pages like Wikipedia
        content = response.content[:500000]  # max 500KB
        page_html = content.decode('utf-8', errors='ignore')
        
        # Check if page is JS-heavy or has low content
        js_indicators = [
            'react', 'vue', 'angular', '__NEXT_DATA__', 
            'window.__', 'ng-app', 'data-reactroot'
        ]
        is_js_heavy = any(ind in page_html.lower() for ind in js_indicators)
        
        # Parse initial content
        soup = BeautifulSoup(page_html, 'lxml')
        page_text = soup.get_text(separator=' ', strip=True)
        word_count = len(page_text.split())
        
        # If JS-heavy OR very low word count, try Playwright
        if is_js_heavy or word_count < 100:
            print(f"JS-heavy site detected, trying Playwright...")
            playwright_content = scrape_with_playwright(url)
            if playwright_content:
                # Limit Playwright content too
                if len(playwright_content) > 500000:
                    playwright_content = playwright_content[:500000]
                soup = BeautifulSoup(playwright_content, 'lxml')
                page_text = soup.get_text(separator=' ', strip=True)
                word_count = len(page_text.split())
                print(f"Playwright succeeded, word count: {word_count}")
        
        page_size = len(page_html) / 1024
        
    except requests.Timeout:
        return {
            "success": False, 
            "error": "Website took too long to respond"
        }
    except requests.ConnectionError:
        return {
            "success": False, 
            "error": "Could not connect to website"
        }
    except Exception as e:
        return {
            "success": False, 
            "error": f"Cannot reach URL: {str(e)}"
        }
    
    issues = []
    score = 100
    
    # --- TITLE ANALYSIS ---
    title_tag = soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else ''
    title_length = len(title)
    
    if not title:
        issues.append({
            "severity": "critical",
            "category": "Title",
            "issue": "No title tag found",
            "fix": "Add a <title> tag to your page head section"
        })
        score -= 15
    elif title_length < 30:
        issues.append({
            "severity": "warning",
            "category": "Title",
            "issue": f"Title too short ({title_length} chars)",
            "fix": "Title should be 50-60 characters for best SEO"
        })
        score -= 5
    elif title_length > 60:
        issues.append({
            "severity": "warning",
            "category": "Title",
            "issue": f"Title too long ({title_length} chars)",
            "fix": "Keep title under 60 characters to avoid truncation"
        })
        score -= 5
    
    # --- META DESCRIPTION ---
    meta_desc_tag = soup.find('meta', attrs={'name': 'description'})
    meta_desc = meta_desc_tag.get('content', '') if meta_desc_tag else ''
    meta_desc_length = len(meta_desc)
    
    if not meta_desc:
        issues.append({
            "severity": "critical",
            "category": "Meta",
            "issue": "No meta description found",
            "fix": "Add <meta name='description' content='...'>"
        })
        score -= 10
    elif meta_desc_length < 120:
        issues.append({
            "severity": "warning",
            "category": "Meta",
            "issue": f"Meta description too short ({meta_desc_length} chars)",
            "fix": "Meta description should be 150-160 characters"
        })
        score -= 5
    elif meta_desc_length > 160:
        issues.append({
            "severity": "warning",
            "category": "Meta",
            "issue": f"Meta description too long ({meta_desc_length} chars)",
            "fix": "Keep meta description under 160 characters"
        })
        score -= 5
    
    # --- HEADINGS ---
    h1_tags = soup.find_all('h1')
    h2_tags = soup.find_all('h2')
    h3_tags = soup.find_all('h3')
    h1_count = len(h1_tags)
    h2_count = len(h2_tags)
    h3_count = len(h3_tags)
    
    if h1_count == 0:
        issues.append({
            "severity": "critical",
            "category": "Headings",
            "issue": "No H1 tag found",
            "fix": "Add exactly one H1 tag as your main page heading"
        })
        score -= 10
    elif h1_count > 1:
        issues.append({
            "severity": "warning",
            "category": "Headings",
            "issue": f"Multiple H1 tags found ({h1_count})",
            "fix": "Use only one H1 tag per page"
        })
        score -= 5
    
    # --- IMAGES ALT TEXT ---
    all_images = soup.find_all('img')
    images_no_alt = [img for img in all_images 
                     if not img.get('alt') or img.get('alt') == '']
    images_total = len(all_images)
    no_alt_count = len(images_no_alt)
    
    if no_alt_count > 0:
        issues.append({
            "severity": "warning",
            "category": "Images",
            "issue": f"{no_alt_count} images missing alt text",
            "fix": "Add descriptive alt attributes to all images"
        })
        score -= min(10, no_alt_count * 2)
    
    # --- LINKS ---
    all_links = soup.find_all('a', href=True)
    base_domain = urlparse(url).netloc
    internal = [l for l in all_links 
                if base_domain in l.get('href','') 
                or l.get('href','').startswith('/')]
    external = [l for l in all_links 
                if l.get('href','').startswith('http') 
                and base_domain not in l.get('href','')]
    internal_count = len(internal)
    external_count = len(external)
    
    # --- CANONICAL ---
    canonical = soup.find('link', attrs={'rel': 'canonical'})
    has_canonical = 1 if canonical else 0
    if not canonical:
        issues.append({
            "severity": "info",
            "category": "Technical",
            "issue": "No canonical tag found",
            "fix": "Add <link rel='canonical' href='...'> to avoid duplicate content"
        })
        score -= 3
    
    # --- OG TAGS ---
    og_title = soup.find('meta', property='og:title')
    og_desc = soup.find('meta', property='og:description')
    og_image = soup.find('meta', property='og:image')
    has_og = 1 if (og_title and og_desc) else 0
    if not has_og:
        issues.append({
            "severity": "info",
            "category": "Social",
            "issue": "Missing Open Graph tags",
            "fix": "Add og:title, og:description, og:image for social sharing"
        })
        score -= 3
    
    # --- WORD COUNT ---
    if word_count < 300:
        issues.append({
            "severity": "warning",
            "category": "Content",
            "issue": f"Low word count ({word_count} words)",
            "fix": "Add more content. Pages with 300+ words rank better"
        })
        score -= 5
    
    # --- ROBOTS META ---
    robots = soup.find('meta', attrs={'name': 'robots'})
    has_robots = 1 if robots else 0
    
    # --- PAGE SPEED ---
    if load_time > 3000:
        issues.append({
            "severity": "warning",
            "category": "Performance",
            "issue": f"Slow page load ({load_time}ms)",
            "fix": "Optimize images, minify CSS/JS, use caching"
        })
        score -= 5
    
    # Keep score between 0 and 100
    score = max(0, min(100, score))
    
    # Sort issues: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))
    
    return {
        "success": True,
        "url": url,
        "overall_score": score,
        "title": title,
        "title_length": title_length,
        "meta_desc": meta_desc,
        "meta_desc_length": meta_desc_length,
        "h1_count": h1_count,
        "h2_count": h2_count,
        "h3_count": h3_count,
        "word_count": word_count,
        "images_total": images_total,
        "images_no_alt": no_alt_count,
        "internal_links": internal_count,
        "external_links": external_count,
        "has_canonical": has_canonical,
        "has_og_tags": has_og,
        "has_robots_meta": has_robots,
        "page_size_kb": round(page_size, 2),
        "load_time_ms": load_time,
        "issues": json.dumps(issues),
        "issues_list": issues
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

@seo_analyzer_bp.route("/seo-analyzer")
@login_required
def page():
    return render_template("seo_analyzer_admin.html", active_page='seo_analyzer')

# ── API Routes ─────────────────────────────────────────────────────────────────--

@seo_analyzer_bp.route("/seo/analyze", methods=["POST"])
@login_required
def analyze():
    """Run SEO analysis on the given URL."""
    try:
        # Accept both JSON and form data
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({"success": False, "error": "URL is required"})
        
        if not url.startswith(('http://', 'https://')):
            return jsonify({"success": False, "error": "URL must start with http:// or https://"})
        
        # Run analysis
        result = analyze_seo(url)
        
        if not result.get('success'):
            return jsonify(result)
        
        # Save to database using direct SQLite for reliability
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO seo_analyses 
            (user_id, url, title, description, seo_score, 
             word_count, heading_structure, link_analysis, image_analysis,
             technical_analysis, recommendations, analysis_date,
             overall_score, title_length, meta_desc, meta_desc_length,
             h1_count, h2_count, h3_count, images_total, images_no_alt,
             internal_links, external_links, has_canonical, has_robots_meta,
             has_og_tags, page_size_kb, load_time_ms, issues, data_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            session.get('user_id', 1),
            result['url'],
            result['title'],
            '',  # description
            result['overall_score'],  # seo_score
            result['word_count'],
            '',  # heading_structure
            '',  # link_analysis
            '',  # image_analysis
            '',  # technical_analysis
            '',  # recommendations
            datetime.now().isoformat(),  # analysis_date
            result['overall_score'],
            result['title_length'],
            result['meta_desc'],
            result['meta_desc_length'],
            result['h1_count'],
            result['h2_count'],
            result['h3_count'],
            result['images_total'],
            result['images_no_alt'],
            result['internal_links'],
            result['external_links'],
            result['has_canonical'],
            result['has_robots_meta'],
            result['has_og_tags'],
            result['page_size_kb'],
            result['load_time_ms'],
            json.dumps(result['issues_list']),
            json.dumps(result),  # data_json
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        print(f"Saved SEO analysis for {url}, score: {result['overall_score']}")
        
        # Log activity using SQLAlchemy
        try:
            activity = ActivityLog(
                user_id=session.get('user_id'),
                event_type='seo',
                title='SEO analysis completed',
                subtitle=url
            )
            db.session.add(activity)
            db.session.commit()
        except:
            pass  # Ignore activity log errors
        
        # Return full result with issues_list as actual list
        result['id'] = 'new'  # Placeholder
        if isinstance(result.get('issues'), str):
            result['issues_list'] = json.loads(result['issues'])
        else:
            result['issues_list'] = result.get('issues_list', [])
        
        print(f"Analysis completed for {url} with score {result.get('overall_score')}")
        return jsonify(result)
        
    except Exception as e:
        print(f"SEO Analysis Error: {str(e)}")
        logger.exception("SEO analysis failed")
        return jsonify({"success": False, "error": "Analysis failed. Please try again."})

@seo_analyzer_bp.route("/seo/history/<int:analysis_id>")
@login_required
def get_analysis(analysis_id):
    """Get a specific saved analysis by ID."""
    try:
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT data_json FROM seo_analyses 
            WHERE id = ? AND user_id = ?
        ''', (analysis_id, session.get('user_id', 1)))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({"success": False, "error": "Analysis not found"})
        
        # Parse the JSON data
        analysis_data = json.loads(row[0])
        analysis_data['success'] = True
        
        return jsonify(analysis_data)
        
    except Exception as e:
        print(f"Get Analysis Error: {str(e)}")
        logger.exception("Failed to load analysis")
        return jsonify({"success": False, "error": "Failed to load analysis"})

@seo_analyzer_bp.route("/seo/history")
@login_required
def history():
    """Get user's SEO analysis history."""
    try:
        import sqlite3
        from datetime import datetime
        
        conn = sqlite3.connect('data/scraper_suite.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, url, overall_score, created_at, title
            FROM seo_analyses 
            WHERE user_id = ?
            ORDER BY created_at DESC 
            LIMIT 10
        ''', (session.get('user_id', 1),))
        
        rows = cursor.fetchall()
        conn.close()
        
        history_list = []
        for row in rows:
            # Extract domain for favicon
            domain = urlparse(row[1]).netloc
            
            # Format time ago
            created = datetime.fromisoformat(row[3])
            now = datetime.now()
            diff = now - created
            
            if diff.seconds < 60:
                time_ago = "Just now"
            elif diff.seconds < 3600:
                time_ago = f"{diff.seconds // 60} mins ago"
            elif diff.days == 0:
                time_ago = f"{diff.seconds // 3600} hours ago"
            else:
                time_ago = f"{diff.days} days ago"
            
            history_list.append({
                "id": row[0],
                "url": row[1],
                "domain": domain,
                "score": row[2] or 0,
                "created_at": time_ago,
                "title": row[4] or 'No title'
            })
        
        return jsonify({"success": True, "history": history_list})
        
    except Exception as e:
        print(f"History Error: {str(e)}")
        logger.exception("Failed to load history")
        return jsonify({"success": False, "error": "Failed to load history"})

# Keep existing routes for compatibility
@seo_analyzer_bp.route("/api/seo-analyzer/user-history")
@login_required
def api_user_history():
    """Legacy route - redirects to new history endpoint."""
    return history()

@seo_analyzer_bp.route("/api/seo-analyzer", methods=["POST"])
@login_required
def api_analyze():
    """Legacy route - redirects to new analyze endpoint."""
    return analyze()
