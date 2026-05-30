"""
Price Tracker Blueprint - Complete robust implementation with SQLite
"""

import logging
import re
import requests
import time
import random
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from flask import Blueprint, current_app, render_template, request, session, jsonify, redirect, url_for
from werkzeug.exceptions import BadRequest, NotFound
from urllib.parse import urlparse

from responses import bad_request, created, not_found, server_error, success
from auth import login_required
from models import db, PriceTrackerEntry, PriceHistory, ActivityLog

logger = logging.getLogger(__name__)

price_tracker_bp = Blueprint("price_tracker", __name__)

# ── Helper Functions ────────────────────────────────────────────────────────

def get_flipkart_price(url):
    import requests
    from bs4 import BeautifulSoup
    import re
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-IN,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }
    
    try:
        session = requests.Session()
        session.headers.update(headers)
        response = session.get(url, timeout=20)
        soup = BeautifulSoup(response.content, 'lxml')
        
        price = None
        
        # Flipkart price selectors
        selectors = [
            '._30jeq3._16Jk6d',
            '._30jeq3',
            '._16Jk6d',
            'div._30jeq3',
            '[class*="_30jeq3"]',
            'div[class*="CEmiEU"]',
            '._25b18 ._30jeq3',
        ]
        
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    cleaned = re.sub(r'[₹,\s]', '', text)
                    nums = re.findall(r'\d+', cleaned)
                    if nums:
                        p = float(nums[0])
                        if p > 50:
                            price = p
                            break
            except:
                continue
        
        # Regex fallback
        if not price:
            text = soup.get_text()
            matches = re.findall(r'₹\s*([\d,]+)', text)
            for m in matches:
                try:
                    p = float(m.replace(',', ''))
                    if 100 < p < 500000:
                        price = p
                        break
                except:
                    continue
        
        return price
        
    except Exception as e:
        print(f"Flipkart price error: {e}")
        return None

def scrape_amazon_price(url, css_selector=None):
    """Amazon-specific scraper with anti-blocking measures."""
    import requests
    import random
    import time
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    ]
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
    }

    session = requests.Session()
    # First visit Amazon homepage to get cookies
    try:
        session.get('https://www.amazon.in', headers=headers, timeout=10)
        time.sleep(random.uniform(1.5, 3.0))
    except:
        pass

    try:
        response = session.get(url, headers=headers, timeout=20)
        if response.status_code == 200 and 'robot' not in response.text.lower():
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Try user-provided CSS selector first - ISSUE 5
            price = None
            if css_selector:
                el = soup.select_one(css_selector)
                if el:
                    raw = el.get_text(strip=True)
                    cleaned = re.sub(r'[₹$,\s]', '', raw)
                    nums = re.findall(r'\d+\.?\d*', cleaned)
                    if nums:
                        p = float(nums[0])
                        if p > 100:
                            price = p
            
            # If no price from user selector, try default selectors
            if not price:
                selectors = [
                    'span.a-price-whole',  # Primary Amazon selector
                    '.a-price .a-offscreen',
                    '#priceblock_ourprice',
                    '#priceblock_dealprice',
                    '#price_inside_buybox',
                    '#newBuyBoxPrice',
                    '#corePrice_feature_div .a-offscreen',
                ]
                for sel in selectors:
                    el = soup.select_one(sel)
                    if el:
                        raw = el.get_text(strip=True)
                        cleaned = re.sub(r'[₹$,\s]', '', raw)
                        nums = re.findall(r'\d+\.?\d*', cleaned)
                        if nums:
                            p = float(nums[0])
                            if p > 100:
                                price = p
                                break

            title_el = soup.select_one('#productTitle')
            title = title_el.get_text(strip=True)[:80] if title_el else 'Amazon Product'

            return {
                'success': True,
                'title': title,
                'price': price,
                'url': url,
                'blocked': price is None
            }
        else:
            return {'success': True, 'title': 'Amazon Product', 'price': None, 'url': url, 'blocked': True}
    except Exception as e:
        print(f"Amazon scrape error: {e}")
        return {'success': False, 'error': str(e)}

def scrape_flipkart_price(url, css_selector=None):
    """Flipkart-specific scraper with improved headers and retry logic."""
    
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36',
    ]
    
    def scrape_with_retry(url, max_retries=3):
        for attempt in range(max_retries):
            try:
                price = _scrape_flipkart_once(url, USER_AGENTS, css_selector)
                if price:
                    return price
                # Wait longer between retries
                time.sleep(random.uniform(2, 5) * (attempt + 1))
            except Exception as e:
                print(f"[SCRAPER] Attempt {attempt+1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
        return None
    
    def _scrape_flipkart_once(url, user_agents, css_selector=None):
        session = requests.Session()
        
        headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,'
                      'application/xml;q=0.9,image/avif,'
                      'image/webp,*/*;q=0.8',
            'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.google.com/',
        }
        
        # Add random delay to avoid rate limiting
        time.sleep(random.uniform(1, 3))
        
        response = session.get(
            url,
            headers=headers,
            timeout=20,
            allow_redirects=True
        )
        
        print(f"[SCRAPER] Status: {response.status_code}")
        print(f"[SCRAPER] URL: {url[:50]}")
        
        if response.status_code in [403, 429, 503]:
            raise Exception(f"Site blocked request: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try user-provided CSS selector first
            if css_selector:
                element = soup.select_one(css_selector)
                if element:
                    price_text = element.get_text()
                    price = _clean_price(price_text)
                    if price:
                        return price
            
            # Try multiple Flipkart price selectors
            selectors = [
                'div._30jeq3',
                'div.Nx9bqj',
                'div._16Jk6d', 
                'div._25b18c ._30jeq3',
                '._30jeq3._16Jk6d',
                'div[class*="price"]',
            ]
            
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    price_text = element.get_text()
                    print(f"[SCRAPER] Found price: {price_text}")
                    price = _clean_price(price_text)
                    if price:
                        return price
            
            # Try meta tags as fallback
            meta = soup.find(
                'meta', 
                {'property': 'product:price:amount'}
            )
            if meta:
                try:
                    return float(meta.get('content', 0))
                except:
                    pass
                    
            print("[SCRAPER] Price not found in page")
            print("[SCRAPER] Page title:", 
                  soup.title.string if soup.title else 'N/A')
            return None
        else:
            print(f"[SCRAPER] Bad status: {response.status_code}")
            return None
    
    def _clean_price(price_text):
        """Clean and extract price from text."""
        import re
        price = re.sub(r'[₹,\s]', '', price_text)
        match = re.search(r'\d+', price)
        if match:
            try:
                return float(match.group())
            except:
                return None
        return None
    
    def _get_title(soup, fallback_title):
        """Extract product title."""
        title_el = soup.select_one('span.B_NuCI')
        if title_el:
            return title_el.get_text(strip=True)[:80]
        else:
            return (fallback_title.replace(' - Buy', '').replace(' Online', '').replace(' at Best Price', '').replace(' - Flipkart.com', '').strip())[:80]
    
    try:
        # Scrape with retry logic
        price = scrape_with_retry(url)
        
        # Get title for successful requests
        title = 'Flipkart Product'
        if price is not None:
            try:
                session = requests.Session()
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                    'Accept-Language': 'en-IN,en;q=0.9',
                }
                
                response = session.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    title = _get_title(soup, response.url)
            except:
                pass
        
        return {
            'success': True,
            'price': price,
            'title': title,
            'url': url,
            'blocked': price is None
        }
        
    except Exception as e:
        print(f"[SCRAPER] Error: {e}")
        return {
            'success': True,
            'price': None,
            'title': 'Flipkart Product',
            'url': url,
            'blocked': False,
            'error': str(e)
        }

def scrape_price_generic(url):
    """Generic scraper for other sites."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-IN,en;q=0.9',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Generic price selectors
            price_selectors = [
                '[class*="price"]',
                '[id*="price"]',
                '[itemprop="price"]',
                '.product-price',
                '.offer-price',
            ]
            
            price = None
            for sel in price_selectors:
                el = soup.select_one(sel)
                if el:
                    raw = el.get_text(strip=True)
                    nums = re.findall(r'[\d,]+\.?\d*', re.sub(r'[₹$€£,]','', raw))
                    if nums:
                        try:
                            price = float(nums[0].replace(',',''))
                            if price > 0:
                                break
                        except:
                            continue
            
            # Generic title
            title_el = soup.find('title')
            title = title_el.get_text(strip=True)[:80] if title_el else 'Unknown Product'
            
            return {
                'success': True,
                'price': price,
                'title': title,
                'url': url,
                'blocked': False
            }
        else:
            return {'success': False, 'error': 'Failed to fetch page'}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_fallback_product_name(url):
    """Generate fallback product name from URL."""
    try:
        domain = urlparse(url).netloc
        domain = domain.replace('www.', '')
        # "flipkart.com" → capitalize first letter
        fallback = domain.split('.')[0].capitalize() + ' Product'
        return fallback
    except:
        return 'Unknown Product'

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

def is_blocked_too_long(product):
    """Check if product has been pending/blocked for more than 30 minutes."""
    if product.current_price is not None:
        return False
    
    if not product.last_checked:
        return False
    
    now = datetime.utcnow()
    if isinstance(product.last_checked, str):
        last_checked = datetime.fromisoformat(product.last_checked.replace('Z', '+00:00'))
    else:
        last_checked = product.last_checked
    
    diff = now - last_checked
    return diff > timedelta(minutes=30)

# ── Page Routes ────────────────────────────────────────────────────────────────

@price_tracker_bp.route("/")
@login_required
def page():
    return render_template("price_tracker_admin.html", active_page='price_tracker')

# ── API Routes ─────────────────────────────────────────────────────────────────--

@price_tracker_bp.route('/add', methods=['POST'])
@login_required
def add_product():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        product_name = data.get('product_name', '').strip()
        frequency = data.get('frequency', 'daily')
        alert_email = data.get('alert_email', '').strip()
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL required'
            })
        
        if not url.startswith(('http://', 'https://')):
            return jsonify({
                'success': False,
                'error': 'Invalid URL format'
            })
        
        user_id = int(session.get('user_id', 0))
        
        import sqlite3, os
        conn = sqlite3.connect(
            os.path.join('data', 'scraper_suite.db')
        )
        
        # Check duplicate
        existing = conn.execute(
            """SELECT id FROM price_tracker_entries 
               WHERE url=? AND user_id=?""",
            (url, user_id)
        ).fetchone()
        
        if existing:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Already tracking this product!'
            })
        
        # Get price - use user provided name if available
        price = None
        if 'flipkart' in url.lower():
            price = get_flipkart_price(url)
        elif 'amazon' in url.lower():
            scraped = scrape_amazon_price(url)
            price = scraped.get('price') if scraped else None
        else:
            scraped = scrape_price_generic(url)
            price = scraped.get('price') if scraped else None
        
        # Use provided product name or scrape title
        final_product_name = product_name
        if not final_product_name:
            if 'flipkart' in url.lower():
                # Try to get title from Flipkart page
                try:
                    import requests
                    from bs4 import BeautifulSoup
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    response = requests.get(url, headers=headers, timeout=10)
                    soup = BeautifulSoup(response.content, 'lxml')
                    title_el = soup.find('span', {'class': 'B_NuCI'}) or soup.find('h1')
                    if title_el:
                        final_product_name = title_el.get_text(strip=True)
                except:
                    pass
            elif 'amazon' in url.lower() and scraped:
                final_product_name = scraped.get('title', 'Unknown Product')
            else:
                final_product_name = scraped.get('title', 'Unknown Product') if scraped else 'Unknown Product'
        
        if not final_product_name:
            final_product_name = 'Unknown Product'
        
        # Always save the product even if price is None
        conn.execute(
            """INSERT INTO price_tracker_entries 
               (user_id, url, product_name, current_price,
                lowest_price, highest_price, frequency, alert_email,
                alert_enabled, is_active, is_blocked, last_checked)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (user_id, url, final_product_name, price,
             price, price, frequency, alert_email if alert_email else None,
             1 if alert_email else 0, 1, 1 if price is None else 0)
        )
        conn.commit()
        conn.close()
        
        print(f"[ADD] Added: {final_product_name} @ ₹{price}")
        
        if price:
            return jsonify({
                'success': True,
                'price': price,
                'name': final_product_name,
                'message': f'Product added! Price found: ₹{price}'
            })
        else:
            return jsonify({
                'success': True,
                'price': None,
                'name': final_product_name,
                'message': 'Product saved! Price will be fetched on next check.'
            })
        
    except Exception as e:
        print(f"[ADD ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })

@price_tracker_bp.route("/products")
@login_required
def get_products():
    """Get all user's tracked products including ones with null price."""
    try:
        import sqlite3
        
        # STEP 1 - Debug prints
        user_id = session.get('user_id')
        print(f"[PT] Session user_id = {user_id}, type = {type(user_id)}")
        
        # Connect to database directly for debugging
        db_path = os.path.join('data', 'scraper_suite.db')
        conn = sqlite3.connect(db_path)
        
        total = conn.execute(
            "SELECT COUNT(*) FROM price_tracker_entries"
        ).fetchone()[0]
        print(f"[PT] Total rows in price_tracker_entries = {total}")
        
        sample = conn.execute(
            "SELECT id, user_id, product_name FROM price_tracker_entries LIMIT 5"
        ).fetchall()
        for s in sample:
            print(f"[PT] Row: id={s[0]}, user_id={s[1]}, name={s[2]}")
        
        # STEP 2 - Load ALL products regardless of user_id
        conn.row_factory = sqlite3.Row
        products = conn.execute(
            """SELECT id, product_name, url, current_price, lowest_price, 
                      highest_price, change_percent, frequency, last_checked, 
                      created_at, user_id, is_active, alert_email, alert_enabled,
                      last_alert_price
               FROM price_tracker_entries 
               ORDER BY created_at DESC"""
        ).fetchall()
        
        print(f"[PT] Products loaded = {len(products)}")
        conn.close()
        
        # Convert Row objects to dict format for JSON response
        result = []
        for product in products:
            product_data = {
                "id": product["id"],
                "product_name": product["product_name"] or "Unknown Product",
                "url": product["url"],
                "current_price": product["current_price"],
                "lowest_price": product["lowest_price"],
                "highest_price": product["highest_price"],
                "change_percent": product["change_percent"],
                "frequency": product["frequency"] or "daily",
                "last_checked": product["last_checked"],
                "created_at": product["created_at"],
                "user_id": product["user_id"],
                "is_active": product["is_active"],
                "alert_email": product["alert_email"],
                "alert_enabled": product["alert_enabled"],
                "last_alert_price": product["last_alert_price"],
                "blocked_too_long": False,
                "is_blocked": 0
            }
            result.append(product_data)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Get products error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify([])

@price_tracker_bp.route("/fetch", methods=["POST"])
@login_required
def fetch_product():
    """Fetch product details from URL."""
    try:
        # Get URL from form data
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()
        
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({"success": False, "error": "URL is required"})
        
        if not url.startswith(('http://', 'https://')):
            return jsonify({"success": False, "error": "URL must start with http:// or https://"})
        
        # Route to appropriate scraper
        try:
            if 'amazon' in url.lower():
                result = scrape_amazon_price(url)
            elif 'flipkart' in url.lower():
                result = scrape_flipkart_price(url)
            else:
                result = scrape_price_generic(url)
            
            print(f"Fetch result for {url}: {result}")
        except Exception as e:
            print(f"[FETCH ERROR] {e}")
            result = {'success': False, 'error': str(e), 'price': None, 'blocked': False}
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Fetch error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@price_tracker_bp.route("/statistics")
@login_required
def get_statistics():
    """Get price tracker statistics."""
    try:
        import sqlite3
        
        user_id = session.get('user_id')
        conn = sqlite3.connect('data/scraper_suite.db')
        
        # Total products
        cursor = conn.execute(
            "SELECT COUNT(*) FROM price_tracker_entries WHERE user_id=?",
            (user_id,)
        )
        total_products = cursor.fetchone()[0]
        
        # Price drops today
        cursor = conn.execute(
            """SELECT COUNT(*) FROM price_tracker_entries 
               WHERE user_id=? AND last_checked >= date('now') 
               AND change_percent < 0""",
            (user_id,)
        )
        price_drops_today = cursor.fetchone()[0]
        
        # Active alerts
        cursor = conn.execute(
            "SELECT COUNT(*) FROM price_tracker_entries WHERE user_id=? AND alert_enabled=1",
            (user_id,)
        )
        active_alerts = cursor.fetchone()[0]
        
        # Total savings (calculate from lowest vs current)
        cursor = conn.execute(
            """SELECT COALESCE(SUM(current_price - lowest_price), 0) 
               FROM price_tracker_entries 
               WHERE user_id=? AND lowest_price IS NOT NULL 
               AND current_price < lowest_price""",
            (user_id,)
        )
        total_savings = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'total_products': total_products,
            'price_drops_today': price_drops_today,
            'active_alerts': active_alerts,
            'total_savings': round(total_savings, 2)
        })
        
    except Exception as e:
        print(f"Statistics error: {e}")
        return jsonify({
            'total_products': 0,
            'price_drops_today': 0,
            'active_alerts': 0,
            'total_savings': 0
        })

@price_tracker_bp.route("/refresh/<int:product_id>", methods=["POST"])
@login_required
def refresh_price(product_id):
    """Refresh price for a specific product."""
    try:
        # Get product from DB
        product = PriceTrackerEntry.query.filter_by(
            id=product_id,
            user_id=session.get('user_id')
        ).first()
        
        if not product:
            return jsonify({
                'success': False, 
                'error': 'Product not found'
            })
        
        # Get CSS selector from product if saved
        css_selector = getattr(product, 'css_selector', None)
        
        # Route to appropriate scraper with CSS selector
        try:
            if 'amazon' in product.url.lower():
                result = scrape_amazon_price(product.url, css_selector)
            elif 'flipkart' in product.url.lower():
                result = scrape_flipkart_price(product.url, css_selector)
            else:
                result = scrape_price_generic(product.url)
            
            print(f"Refresh result for {product.url}: {result}")
        except Exception as e:
            print(f"[SCRAPE ERROR] {e}")
            result = {'success': False, 'error': str(e), 'price': None, 'blocked': False}
        
        # Update blocking status
        if result.get('blocked'):
            product.is_blocked = 1
        elif result['success'] and result['price']:
            product.is_blocked = 0
        
        if result['success'] and result['price']:
            new_price = result['price']
            old_price = product.current_price
            
            # Calculate change
            change = None
            if old_price and old_price > 0:
                change = round(
                    ((new_price - old_price) / old_price) * 100, 
                    2)
            
            # Update lowest/highest
            lowest = product.lowest_price
            highest = product.highest_price
            
            if lowest is None or new_price < lowest:
                lowest = new_price
            if highest is None or new_price > highest:
                highest = new_price
            
            # Store old price for alert comparison
            old_price = product.current_price
            
            # Update product
            product.current_price = new_price
            product.lowest_price = lowest
            product.highest_price = highest
            product.change_percent = change
            product.last_checked = datetime.utcnow()
            product.product_name = result.get('title', product.product_name)
            
            # Handle fallback title if needed
            if not product.product_name or product.product_name == 'Unknown Product':
                product.product_name = get_fallback_product_name(product.url)
            
            db.session.commit()
            
            # Send price alert if price changed
            if (old_price and new_price and old_price != new_price and
                product.alert_enabled and product.alert_email):
                
                # Avoid duplicate alerts for same price
                if product.last_alert_price != new_price:
                    change_type = 'drop' if new_price < old_price else 'increase'
                    
                    # Import alert function from auth
                    from auth import send_price_alert
                    
                    sent = send_price_alert(
                        to_email=product.alert_email,
                        product_name=product.product_name,
                        product_url=product.url,
                        old_price=old_price,
                        new_price=new_price,
                        change_type=change_type
                    )
                    
                    if sent:
                        # Update last alert price
                        product.last_alert_price = new_price
                        db.session.commit()
            
            # Add to price history
            try:
                history = PriceHistory(
                    product_id=product_id,
                    price=new_price,
                    recorded_at=datetime.utcnow()
                )
                db.session.add(history)
                db.session.commit()
            except:
                pass  # History table might not exist
            
            return jsonify({
                'success': True,
                'price': new_price,
                'change': change,
                'lowest': lowest,
                'highest': highest,
                'message': f'Price updated: ₹{new_price:,.0f}'
            })
        else:
            # Update last_checked even if failed
            product.last_checked = datetime.utcnow()
            
            # Check if it's a blocked request
            error_msg = result.get('error', '')
            if 'blocked request' in error_msg.lower() or result.get('blocked', False):
                product.is_blocked = 1
                db.session.commit()
                return jsonify({
                    'error': 'blocked',
                    'message': 'Flipkart is blocking automated requests. '
                               'Try again in a few minutes.',
                    'retry_after': 300  # 5 minutes
                }), 429
            else:
                # Update status to pending for other errors
                product.is_blocked = 0
                db.session.commit()
                return jsonify({
                    'success': False,
                    'blocked': result.get('blocked', False),
                    'error': result.get('error', 'Could not fetch price')
                })
            
    except Exception as e:
        print(f"Refresh error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })

@price_tracker_bp.route('/delete/<int:product_id>', 
                 methods=['GET', 'POST', 'DELETE'])
def delete_product(product_id):
    import sqlite3, os
    try:
        db_path = os.path.join('data', 'scraper_suite.db')
        conn = sqlite3.connect(db_path)
        
        print(f"[DELETE] Deleting id={product_id}")
        
        conn.execute(
            "DELETE FROM price_tracker_entries WHERE id=?",
            (product_id,)
        )
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"[DELETE ERROR] {e}")
        return jsonify({'success': False, 'error': str(e)})
