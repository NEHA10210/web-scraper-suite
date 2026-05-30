"""
Authentication blueprint: signup, login, logout, protected routes.
"""

import json
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, flash,
    Response, make_response, send_file
)
from werkzeug.security import check_password_hash
from models import db, User, ScrapedData
from responses import success, not_found
from datetime import datetime
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Gmail SMTP config
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_EMAIL = 'your-app-email@gmail.com'  
SMTP_PASSWORD = 'your-app-password'

# HOW TO SET UP GMAIL SMTP:
# 1. Go to Google Account → Security
# 2. Enable 2-Step Verification
# 3. Go to App Passwords
# 4. Generate password for "Mail" + "Windows Computer"
# 5. Copy the 16-char password
# 6. Set SMTP_EMAIL = 'your-gmail@gmail.com'
# 7. Set SMTP_PASSWORD = 'xxxx xxxx xxxx xxxx'

def format_dt(raw):
    if not raw:
        return '—'
    try:
        # Remove microseconds
        clean = str(raw).split('.')[0].replace('T', ' ')
        dt = datetime.strptime(clean, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%d %b %Y, %I:%M %p')
    except:
        return str(raw)

auth_bp = Blueprint('auth', __name__)

def login_required(f):
    """Decorator to require login."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        # Validation
        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('signup.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('signup.html')

        # Check if user exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.', 'danger')
            return render_template('signup.html')

        # Create user
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('signup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session.permanent = remember
            flash(f'Welcome back, {user.name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            return render_template('login.html')

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

# Create price history table if it doesn't exist
def ensure_price_history_table():
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    
    # Drop existing table if it has wrong schema
    conn.execute("DROP TABLE IF EXISTS price_history")
    
    # Create table with correct schema matching PriceHistory model
    conn.execute("""
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            recorded_at DATETIME DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) 
                REFERENCES price_tracker_entries(id)
        )
    """)
    
    # Migrate existing products to history table
    conn.execute("""
        INSERT INTO price_history (product_id, price, recorded_at)
        SELECT id, current_price, last_checked
        FROM price_tracker_entries
        WHERE current_price IS NOT NULL
    """)
    conn.commit()
    conn.close()

ensure_price_history_table()

# Add alert columns to price_tracker_entries table
def ensure_alert_columns():
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    
    # Add alert columns if they don't exist
    sql_statements = [
        "ALTER TABLE price_tracker_entries ADD COLUMN alert_email TEXT",
        "ALTER TABLE price_tracker_entries ADD COLUMN target_price REAL",
        "ALTER TABLE price_tracker_entries ADD COLUMN alert_enabled INTEGER DEFAULT 1",
        "ALTER TABLE price_tracker_entries ADD COLUMN last_alert_price REAL"
    ]
    
    for sql in sql_statements:
        try:
            conn.execute(sql)
            print(f"[DB] Added column: {sql}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    
    conn.commit()
    conn.close()

ensure_alert_columns()

def send_price_alert(
    to_email, product_name, product_url,
    old_price, new_price, change_type
):
    try:
        # Determine change direction
        if change_type == 'drop':
            subject = f"🟢 Price Drop Alert: {product_name}"
            change_text = "dropped"
            change_color = "#22c55e"
            change_icon = "📉"
            savings = old_price - new_price
            extra_line = f"""
            <p style="color:#22c55e;font-size:16px;
                      font-weight:600;text-align:center;">
                You save Rs.{savings:,.0f}!
            </p>"""
        else:
            subject = f"🔴 Price Increase Alert: {product_name}"
            change_text = "increased"
            change_color = "#ef4444"
            change_icon = "📈"
            extra_line = ""

        diff = abs(new_price - old_price)
        pct = abs((new_price - old_price) / old_price * 100)

        # HTML email body
        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;
                     background-color:#0f172a;
                     font-family:-apple-system,sans-serif;">
            <div style="max-width:560px;margin:0 auto;
                        padding:32px 16px;">
                
                <!-- Header -->
                <div style="background:linear-gradient(135deg,
                            #00d4ff,#7c3aed);
                            border-radius:12px 12px 0 0;
                            padding:24px;text-align:center;">
                    <div style="font-size:36px;">🌐</div>
                    <div style="color:white;font-size:20px;
                                font-weight:700;margin-top:8px;">
                        Scraper Suite
                    </div>
                    <div style="color:rgba(255,255,255,0.8);
                                font-size:13px;margin-top:4px;">
                        Price Alert Notification
                    </div>
                </div>

                <!-- Body -->
                <div style="background:#1e293b;
                            border-radius:0 0 12px 12px;
                            padding:28px;">
                    
                    <div style="text-align:center;
                                margin-bottom:24px;">
                        <span style="font-size:40px;">
                            {change_icon}
                        </span>
                        <h2 style="color:white;margin:12px 0 4px;">
                            Price {change_text.title()}!
                        </h2>
                        <p style="color:#94a3b8;margin:0;
                                  font-size:14px;">
                            {product_name}
                        </p>
                    </div>

                    <!-- Price comparison -->
                    <div style="display:flex;
                                justify-content:space-around;
                                background:#0f172a;
                                border-radius:10px;
                                padding:20px;
                                margin-bottom:20px;">
                        <div style="text-align:center;">
                            <div style="color:#64748b;
                                        font-size:11px;
                                        text-transform:uppercase;
                                        letter-spacing:1px;">
                                Old Price
                            </div>
                            <div style="color:#94a3b8;
                                        font-size:22px;
                                        font-weight:700;
                                        margin-top:6px;
                                        text-decoration:line-through;">
                                Rs.{old_price:,.0f}
                            </div>
                        </div>
                        <div style="text-align:center;
                                    padding:0 16px;">
                            <div style="color:{change_color};
                                        font-size:28px;">→</div>
                            <div style="color:{change_color};
                                        font-size:12px;
                                        font-weight:600;">
                                {pct:.1f}%
                            </div>
                        </div>
                        <div style="text-align:center;">
                            <div style="color:#64748b;
                                        font-size:11px;
                                        text-transform:uppercase;
                                        letter-spacing:1px;">
                                New Price
                            </div>
                            <div style="color:{change_color};
                                        font-size:22px;
                                        font-weight:700;
                                        margin-top:6px;">
                                Rs.{new_price:,.0f}
                            </div>
                        </div>
                    </div>

                    <!-- Change amount -->
                    <div style="background:rgba({
                        '34,197,94' if change_type=='drop' 
                        else '239,68,68'
                    },0.1);
                                border:1px solid {change_color};
                                border-radius:8px;
                                padding:12px;
                                text-align:center;
                                margin-bottom:20px;">
                        <span style="color:{change_color};
                                     font-weight:600;">
                            Price {change_text} by 
                            Rs.{diff:,.0f} ({pct:.1f}%)
                        </span>
                    </div>

                    {extra_line}

                    <!-- CTA Button -->
                    <div style="text-align:center;
                                margin:24px 0 16px;">
                        <a href="{product_url}"
                           style="background:linear-gradient(
                                      135deg,#00d4ff,#0ea5e9);
                                  color:#0f172a;
                                  padding:14px 32px;
                                  border-radius:8px;
                                  text-decoration:none;
                                  font-weight:700;
                                  font-size:15px;
                                  display:inline-block;">
                            View Product →
                        </a>
                    </div>

                    <!-- Footer -->
                    <div style="border-top:1px solid 
                                rgba(255,255,255,0.08);
                                margin-top:24px;
                                padding-top:16px;
                                text-align:center;">
                        <p style="color:#475569;font-size:12px;">
                            This alert was sent by Scraper Suite.<br>
                            You're tracking this product on 
                            Price Tracker.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Scraper Suite <{SMTP_EMAIL}>"
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, 
                          msg.as_string())

        print(f"[EMAIL] Alert sent to {to_email} "
              f"for {product_name}")
        return True

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

@auth_bp.route('/api/dashboard/history')
@login_required
def api_history():
    """Return current user's scraping history."""
    user_id = session.get('user_id')
    records = ScrapedData.query.filter_by(user_id=user_id).order_by(ScrapedData.created_at.desc()).limit(20).all()
    history = [
        {
            'id': r.id,
            'url': r.url,
            'scrape_type': r.scrape_type,
            'use_dynamic': r.use_dynamic,
            'created_at': r.created_at.isoformat()
        }
        for r in records
    ]
    return success({'history': history})

@auth_bp.route('/api/dashboard/history/<int:record_id>')
@login_required
def api_history_record(record_id):
    """Return a specific scraping result for the current user."""
    user_id = session.get('user_id')
    record = ScrapedData.query.filter_by(id=record_id, user_id=user_id).first()
    if not record:
        return not_found('Record not found')
    try:
        result = json.loads(record.result_json)
    except Exception:
        result = {}
    return success({'result': result})

@auth_bp.route('/dashboard/debug')
def dashboard_debug():
    """Comprehensive debug route to see actual database structure and data."""
    import sqlite3, os, json
    from flask import jsonify
    
    result = {}
    
    # Find DB file
    for root, dirs, files in os.walk('.'):
        for f in files:
            if f.endswith(('.db', '.sqlite', '.sqlite3')):
                db_path = os.path.join(root, f)
                try:
                    conn = sqlite3.connect(db_path)
                    tables = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    result[db_path] = {}
                    for (t,) in tables:
                        cols = conn.execute(
                            f"PRAGMA table_info({t})"
                        ).fetchall()
                        sample = conn.execute(
                            f"SELECT * FROM {t} LIMIT 2"
                        ).fetchall()
                        result[db_path][t] = {
                            'columns': [c[1] for c in cols],
                            'sample_rows': len(sample),
                            'total': conn.execute(
                                f"SELECT COUNT(*) FROM {t}"
                            ).fetchone()[0]
                        }
                    conn.close()
                except Exception as e:
                    result[db_path] = str(e)
    
    return jsonify(result)

def get_user_id_variants(user_id):
    variants = []
    try:
        variants.append(int(user_id))
    except:
        pass
    try:
        variants.append(str(user_id))
    except:
        pass
    return variants

@auth_bp.route('/dashboard/stats')
def dashboard_stats():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    
    user_id = session['user_id']
    
    import sqlite3, datetime, os
    from flask import jsonify
    DB_PATH = os.path.join('data', 'scraper_suite.db')
    
    response = {
        'total_scrapes_today': 0,
        'active_jobs': 0,
        'seo_analyses': 0,
        'success_rate': 0.0,
        'recent_activity': [],
        'performance': {
            '7days': generate_empty_days(7),
            '30days': generate_empty_days(30),
            '90days': generate_empty_days(90)
        }
    }
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        today = datetime.date.today().isoformat()
        
        # Active Jobs
        try:
            count = 0
            for uid in get_user_id_variants(user_id):
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM price_tracker_entries WHERE user_id=?",
                    (uid,)
                ).fetchone()
                count = row['cnt'] if row else 0
                if count > 0:
                    break
            response['active_jobs'] = count
            print(f"[DEBUG] active_jobs={response['active_jobs']}")
        except Exception as e:
            print(f"active_jobs error: {e}")
        
        # SEO Analyses  
        try:
            count = 0
            for uid in get_user_id_variants(user_id):
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM seo_analyses WHERE user_id=?",
                    (uid,)
                ).fetchone()
                count = row['cnt'] if row else 0
                if count > 0:
                    break
            response['seo_analyses'] = count
            print(f"[DEBUG] seo_analyses={response['seo_analyses']}")
        except Exception as e:
            print(f"seo_analyses error: {e}")
        
        # Total Scrapes = ALL time scrape_jobs with type casting
        try:
            # Try int first
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM scrape_jobs WHERE user_id=?",
                (int(user_id) if user_id else 0,)
            ).fetchone()
            count = row['cnt'] if row else 0
            
            # If 0, try string version
            if count == 0:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM scrape_jobs WHERE user_id=?",
                    (str(user_id),)
                ).fetchone()
                count = row['cnt'] if row else 0
            
            # If still 0, just count all jobs (no user filter)
            if count == 0:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM scrape_jobs"
                ).fetchone()
                count = row['cnt'] if row else 0
            
            response['total_scrapes_today'] = count
            print(f"[DEBUG] total_scrapes_today={response['total_scrapes_today']}")
        except Exception as e:
            print(f"total_scrapes error: {e}")
        
        # Success Rate
        try:
            total = 0
            success = 0
            for uid in get_user_id_variants(user_id):
                t = conn.execute(
                    "SELECT COUNT(*) as cnt FROM scrape_jobs WHERE user_id=?",
                    (uid,)
                ).fetchone()
                total = t['cnt'] if t else 0
                if total > 0:
                    s = conn.execute(
                        "SELECT COUNT(*) as cnt FROM scrape_jobs WHERE user_id=? AND status='completed'",
                        (uid,)
                    ).fetchone()
                    success = s['cnt'] if s else 0
                    break
            if total > 0:
                response['success_rate'] = round((success / total) * 100, 1)
            print(f"[DEBUG] success_rate={response['success_rate']}")
        except Exception as e:
            print(f"success_rate error: {e}")
        
        # Recent Activity
        try:
            rows = []
            for uid in get_user_id_variants(user_id):
                rows = conn.execute(
                    """SELECT event_type, title, subtitle, created_at
                       FROM activity_logs WHERE user_id=?
                       ORDER BY created_at DESC LIMIT 10""",
                    (uid,)
                ).fetchall()
                if rows:
                    break
            activities = []
            for row in rows:
                icon_map = {'price':'🏷️','seo':'📊','scrape':'🌐'}
                event = row['event_type'] or ''
                icon = next((v for k,v in icon_map.items() if k in event.lower()), '⚡')
                activities.append({
                    'type': row['event_type'],
                    'description': row['title'],
                    'timestamp': row['created_at'],
                    'status': 'success',
                    'icon': icon
                })
            response['recent_activity'] = activities
            print(f"[DEBUG] recent_activity count={len(activities)}")
        except Exception as e:
            print(f"recent_activity error: {e}")
        
        # Performance chart = scrape_jobs by day
        try:
            for period_key, days in [('7days',7),('30days',30),('90days',90)]:
                perf = []
                for i in range(days - 1, -1, -1):
                    d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
                    total = 0
                    succ = 0
                    for uid in get_user_id_variants(user_id):
                        row = conn.execute(
                            """SELECT
                               COUNT(*) as total,
                               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as successful
                               FROM scrape_jobs
                               WHERE user_id=? AND DATE(created_at)=?""",
                            (uid, d)
                        ).fetchone()
                        total = row['total'] if row else 0
                        if total > 0:
                            succ = int(row['successful'] or 0) if row else 0
                            break
                    perf.append({
                        'date': d,
                        'successful': succ,
                        'failed': total - succ
                    })
                response['performance'][period_key] = perf
        except Exception as e:
            print(f"performance error: {e}")
        
        conn.close()
        
    except Exception as e:
        print(f"[DASHBOARD ERROR] {e}")
    
    return jsonify(response)

def generate_empty_days(n):
    import datetime
    return [
        {
            'date': (datetime.date.today() - datetime.timedelta(days=i)).isoformat(),
            'successful': 0,
            'failed': 0
        }
        for i in range(n - 1, -1, -1)
    ]

def format_time_ago(timestamp):
    """Format timestamp as 'X ago' string."""
    if not timestamp:
        return 'Unknown'
    
    try:
        from datetime import datetime
        if isinstance(timestamp, str):
            created = datetime.fromisoformat(timestamp.replace(' ', 'T'))
        else:
            created = timestamp
        
        diff = datetime.now() - created
        if diff.total_seconds() < 60:
            return 'Just now'
        elif diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds()//60)}m ago"
        elif diff.days == 0:
            return f"{int(diff.total_seconds()//3600)}h ago"
        else:
            return f"{diff.days}d ago"
    except:
        return 'Recently'


@auth_bp.route('/settings/update', methods=['POST'])
def settings_update():
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    
    import sqlite3, os
    
    # Handle both form and JSON data
    data = request.get_json() if request.is_json else request.form
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    user_id = session.get('user_id')
    
    try:
        conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
        
        # Try int user_id first
        try:
            uid = int(user_id)
        except:
            uid = user_id
        
        # Try 'name' column first, then 'username'
        try:
            if name:
                conn.execute("UPDATE users SET name=?, email=? WHERE id=?", (name, email, uid))
        except:
            if name:
                conn.execute("UPDATE users SET username=?, email=? WHERE id=?", (name, email, uid))
        
        conn.commit()
        conn.close()
        
        # UPDATE SESSION immediately
        session['username'] = name
        session['name'] = name
        session['email'] = email
        session.modified = True
        
        print(f"[PROFILE] Saved: {name}, {email}")
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"[PROFILE ERROR] {e}")
        return jsonify({'success': False, 'error': str(e)})

@auth_bp.route('/price-tracker/export/csv')
def export_price_tracker_csv():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    import csv, io
    import sqlite3, os
    
    uid = int(session['user_id'])
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    products = conn.execute(
        """SELECT product_name, url, current_price, 
           lowest_price, highest_price, change_percent,
           frequency, last_checked, is_blocked
           FROM price_tracker_entries 
           WHERE user_id=? ORDER BY created_at DESC""",
        (uid,)
    ).fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow([
        'Product Name', 'URL', 'Current Price (₹)',
        'Lowest Price (₹)', 'Highest Price (₹)', 
        'Change %', 'Frequency', 'Last Checked', 'Status'
    ])
    
    # Data rows
    for p in products:
        writer.writerow([
            p['product_name'] or 'Unknown',
            p['url'],
            p['current_price'] or 'Pending',
            p['lowest_price'] or '-',
            p['highest_price'] or '-',
            f"{p['change_percent'] or 0}%",
            p['frequency'] or 'Daily',
            p['last_checked'] or '-',
            'Blocked' if p['is_blocked'] else 'Active'
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': 
            f'attachment;filename=price_tracker_export_{datetime.now().strftime("%Y-%m-%d")}.csv'
        }
    )


@auth_bp.route('/price-tracker/history/<int:entry_id>')
def price_history(entry_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    # Get product info
    product = conn.execute("""
        SELECT product_name, url, current_price,
               lowest_price, highest_price
        FROM price_tracker_entries
        WHERE id = ? AND user_id = ?
    """, (entry_id, user_id)).fetchone()
    
    if not product:
        return jsonify({'error': 'Not found'}), 404
    
    # Get price history
    history = conn.execute("""
        SELECT price, recorded_at
        FROM price_history
        WHERE product_id = ?
        ORDER BY recorded_at ASC
        LIMIT 30
    """, (entry_id,)).fetchall()
    
    # If no history, generate demo data from current price
    # so chart always has something to show
    history_data = []
    if history:
        for h in history:
            history_data.append({
                'price': h['price'],
                'date': h['recorded_at']
            })
    elif product['current_price']:
        # Generate last 7 days demo data
        from datetime import datetime, timedelta
        import random
        base = product['current_price']
        for i in range(7):
            day = datetime.now() - timedelta(days=6-i)
            variation = random.uniform(-0.05, 0.05)
            history_data.append({
                'price': round(base * (1 + variation), 2),
                'date': day.strftime('%Y-%m-%d %H:%M:%S')
            })
    
    conn.close()
    return jsonify({
        'product_name': product['product_name'],
        'current_price': product['current_price'],
        'lowest_price': product['lowest_price'],
        'highest_price': product['highest_price'],
        'history': history_data
    })


@auth_bp.route('/price-tracker/toggle-alert/<int:entry_id>', methods=['POST'])
def toggle_alert(entry_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    
    product = conn.execute("""
        SELECT alert_enabled FROM price_tracker_entries
        WHERE id = ? AND user_id = ?
    """, (entry_id, session['user_id'])).fetchone()
    
    if not product:
        conn.close()
        return jsonify({'error': 'Product not found'}), 404
    
    new_state = 0 if product['alert_enabled'] else 1
    conn.execute("""
        UPDATE price_tracker_entries
        SET alert_enabled = ?
        WHERE id = ? AND user_id = ?
    """, (new_state, entry_id, session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({'alert_enabled': new_state})


# GET profile page
@auth_bp.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    # DEBUG - print everything
    tables = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table'
    """).fetchall()
    print("=== PROFILE DEBUG ===")
    print("Tables:", [t[0] for t in tables])
    print("Session user_id:", session.get('user_id'))
    print("Session:", dict(session))
    
    # Check each table for user_id column
    for table in tables:
        tname = table[0]
        try:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {tname}"
            ).fetchone()[0]
            print(f"Table '{tname}': {count} total rows")
            
            # Check if has user_id
            try:
                ucount = conn.execute(
                    f"SELECT COUNT(*) FROM {tname} "
                    f"WHERE user_id = ?",
                    (session['user_id'],)
                ).fetchone()[0]
                print(f"  → {ucount} rows for this user")
            except:
                print(f"  → no user_id column")
        except Exception as e:
            print(f"Table '{tname}' error: {e}")
    
    print("=== END DEBUG ===")
    
    user = conn.execute("""
        SELECT id, name, email, created_at
        FROM users
        WHERE id = ?
    """, (session['user_id'],)).fetchone()
    
    # Debug: Print user data
    print("User row keys:", user.keys())
    print("User data:", dict(user))
    
    # Convert sqlite3.Row to dict
    user_dict = dict(user)
    print("User dict:", user_dict)
    
    # Debug: Check actual table names
    tables = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table'
    """).fetchall()
    print("Tables:", [t[0] for t in tables])
    
    # First print ALL table names to terminal
    tables = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table'
    """).fetchall()
    print("[PROFILE] All tables:", [t[0] for t in tables])
    
    # Then use the correct table names based on output.
    # Common variations - try each:
    
    # For scrape jobs:
    try:
        total_scrapes = conn.execute("""
            SELECT COUNT(*) FROM scrape_jobs 
            WHERE user_id = ?
        """, (session['user_id'],)).fetchone()[0]
    except:
        try:
            total_scrapes = conn.execute("""
                SELECT COUNT(*) FROM scraping_jobs 
                WHERE user_id = ?
            """, (session['user_id'],)).fetchone()[0]
        except:
            total_scrapes = 0
    
    print("[PROFILE] total_scrapes:", total_scrapes)
    
    # For price tracker:
    try:
        total_tracked = conn.execute("""
            SELECT COUNT(*) FROM price_tracker_entries 
            WHERE user_id = ?
        """, (session['user_id'],)).fetchone()[0]
    except:
        try:
            total_tracked = conn.execute("""
                SELECT COUNT(*) FROM tracked_products 
                WHERE user_id = ?
            """, (session['user_id'],)).fetchone()[0]
        except:
            total_tracked = 0
    
    print("[PROFILE] total_tracked:", total_tracked)
    
    # For SEO:
    try:
        total_seo = conn.execute("""
            SELECT COUNT(*) FROM seo_analyses 
            WHERE user_id = ?
        """, (session['user_id'],)).fetchone()[0]
    except:
        try:
            total_seo = conn.execute("""
                SELECT COUNT(*) FROM seo_results 
                WHERE user_id = ?
            """, (session['user_id'],)).fetchone()[0]
        except:
            try:
                total_seo = conn.execute("""
                    SELECT COUNT(*) FROM seo_jobs 
                    WHERE user_id = ?
                """, (session['user_id'],)).fetchone()[0]
            except:
                total_seo = 0
    
    print("[PROFILE] total_seo:", total_seo)
    
    conn.close()
    return render_template('profile.html',
        user=user_dict,
        username=user_dict.get('name') or user_dict.get('username'),
        total_scrapes=total_scrapes,
        total_tracked=total_tracked,
        total_seo=total_seo
    )

# Settings page
@auth_bp.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    user = conn.execute("""
        SELECT id, name, email, created_at
        FROM users
        WHERE id = ?
    """, (session['user_id'],)).fetchone()
    
    user = dict(user)
    conn.close()
    return render_template('settings.html', user=user)

# POST update profile
@auth_bp.route('/profile/update', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    
    if not username or not email:
        return jsonify({'error': 'Name and email required'}), 400
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    
    # Check email not taken by another user
    existing = conn.execute("""
        SELECT id FROM users 
        WHERE email = ? AND id != ?
    """, (email, session['user_id'])).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'error': 'Email already in use'}), 400
    
    conn.execute("""
        UPDATE users SET name = ?, email = ?
        WHERE id = ?
    """, (username, email, session['user_id']))
    conn.commit()
    
    # Update session
    session['username'] = username
    session['email'] = email
    
    conn.close()
    return jsonify({'success': True, 
                    'message': 'Profile updated!'})

# POST change password
@auth_bp.route('/profile/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    current_pw = data.get('current_password', '')
    new_pw = data.get('new_password', '')
    confirm_pw = data.get('confirm_password', '')
    
    if not all([current_pw, new_pw, confirm_pw]):
        return jsonify({'error': 'All fields required'}), 400
    
    if new_pw != confirm_pw:
        return jsonify({'error': 'Passwords do not match'}), 400
    
    if len(new_pw) < 6:
        return jsonify({
            'error': 'Password must be at least 6 characters'
        }), 400
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    user = conn.execute("""
        SELECT password_hash FROM users WHERE id = ?
    """, (session['user_id'],)).fetchone()
    
    # Verify current password
    import werkzeug.security as ws
    if not ws.check_password_hash(user['password_hash'], current_pw):
        conn.close()
        return jsonify({'error': 'Current password is wrong'}), 400
    
    new_hash = ws.generate_password_hash(new_pw)
    conn.execute("""
        UPDATE users SET password_hash = ? WHERE id = ?
    """, (new_hash, session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 
                    'message': 'Password changed!'})

# POST delete account
@auth_bp.route('/profile/delete-account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    password = data.get('password', '')
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    user = conn.execute("""
        SELECT password_hash FROM users WHERE id = ?
    """, (session['user_id'],)).fetchone()
    
    import werkzeug.security as ws
    if not ws.check_password_hash(user['password_hash'], password):
        conn.close()
        return jsonify({'error': 'Wrong password'}), 400
    
    user_id = session['user_id']
    
    # Delete all user data
    for table in ['scrape_jobs', 'price_tracker_entries', 
                  'seo_analyses', 'price_history']:
        try:
            conn.execute(f"""
                DELETE FROM {table} WHERE user_id = ?
            """, (user_id,))
        except:
            pass
    
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    session.clear()
    return jsonify({'success': True})


@auth_bp.route('/price-tracker/export/pdf')
def export_price_tracker_pdf():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (SimpleDocTemplate, Table, 
        TableStyle, Paragraph, Spacer)
    from reportlab.lib.units import inch
    import io, sqlite3, os
    from datetime import datetime
    
    uid = int(session['user_id'])
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    products = conn.execute(
        """SELECT product_name, url, current_price,
           lowest_price, highest_price, change_percent,
           frequency, last_checked
           FROM price_tracker_entries
           WHERE user_id=? ORDER BY created_at DESC""",
        (uid,)
    ).fetchall()
    conn.close()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(A4),
        rightMargin=30, leftMargin=30,
        topMargin=30, bottomMargin=30
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    title = Paragraph(
        "<b>Price Tracker Report</b>", 
        styles['Title']
    )
    elements.append(title)
    
    subtitle = Paragraph(
        f"Generated on {datetime.now().strftime('%d %b %Y %H:%M')}",
        styles['Normal']
    )
    elements.append(subtitle)
    elements.append(Spacer(1, 20))
    
    # Table data
    data = [[
        'Product Name', 'Current Price', 
        'Lowest', 'Highest', 'Change', 'Frequency'
    ]]
    
    for p in products:
        name = str(p['product_name'] or 'Unknown')[:40]
        data.append([
            name,
            f"₹{p['current_price']}" if p['current_price'] else 'Pending',
            f"₹{p['lowest_price']}" if p['lowest_price'] else '-',
            f"₹{p['highest_price']}" if p['highest_price'] else '-',
            f"{p['change_percent'] or 0}%",
            p['frequency'] or 'Daily'
        ])
    
    table = Table(data, colWidths=[
        3*inch, 1.2*inch, 1.2*inch, 
        1.2*inch, 0.9*inch, 1*inch
    ])
    
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E293B')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#06B6D4')),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 11),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('TOPPADDING', (0,0), (-1,0), 12),
        # Data rows
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#E2E8F0')),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('ALIGN', (1,1), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), 
         [colors.HexColor('#0F172A'), colors.HexColor('#1E293B')]),
        # Grid
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#334155')),
        ('ROUNDEDCORNERS', [5]),
        ('TOPPADDING', (0,1), (-1,-1), 8),
        ('BOTTOMPADDING', (0,1), (-1,-1), 8),
    ]))
    
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition':
            'attachment;filename=price_tracker_report.pdf'
        }
    )


@auth_bp.route('/data-scraper/export/csv/<int:job_id>')
def export_scraper_csv(job_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    import csv, io, json
    import sqlite3, os
    
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    job = conn.execute(
        "SELECT * FROM scrape_jobs WHERE id=?", 
        (job_id,)
    ).fetchone()
    conn.close()
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Type', 'Status', 
                     'Records Found', 'Created At'])
    writer.writerow([
        job['url'], job['scrape_type'],
        job['status'], job['records_found'],
        job['created_at']
    ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition':
            f'attachment;filename=scrape_job_{job_id}.csv'
        }
    )


@auth_bp.route('/data-scraper/export/all/csv')
def export_all_scraper_csv():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    import csv, io, sqlite3, os
    uid = int(session['user_id'])
    conn = sqlite3.connect(os.path.join('data','scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    jobs = conn.execute(
        """SELECT 
            url,
            scrape_type as type,
            SUM(records_found) as total_records,
            COUNT(*) as total_runs,
            MAX(created_at) as last_scraped
        FROM scrape_jobs 
        WHERE user_id = ?
        GROUP BY url, scrape_type
        ORDER BY last_scraped DESC""",
        (uid,)
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['URL', 'Type', 'Total Records', 'Runs', 'Last Scraped'])
    for j in jobs:
        writer.writerow([
            j['url'], 
            j['type'], 
            j['total_records'], 
            j['total_runs'],
            format_dt(j['last_scraped'])
        ])
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = \
        'attachment; filename=all_scrape_jobs.csv'
    return response


@auth_bp.route('/api/search')
def global_search():
    if 'user_id' not in session:
        return jsonify([])
    
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    user_id = session['user_id']
    results = []
    
    import sqlite3, os
    conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
    conn.row_factory = sqlite3.Row
    
    # Search Data Scraper jobs
    scraper_jobs = conn.execute("""
        SELECT url, scrape_type, 
               SUM(records_found) as records_found,
               MAX(created_at) as created_at
        FROM scrape_jobs
        WHERE user_id = ? AND url LIKE ?
        GROUP BY url, scrape_type
        ORDER BY created_at DESC
        LIMIT 3
    """, (user_id, f'%{query}%')).fetchall()
    
    for job in scraper_jobs:
        results.append({
            'type': 'scraper',
            'icon': '🌐',
            'title': job['url'],
            'subtitle': f"{job['scrape_type']} · {job['records_found']} records",
            'url': '/data-scraper',
            'badge': 'Data Scraper',
            'badge_color': '#00d4ff'
        })
    
    # Search Price Tracker products
    price_products = conn.execute("""
        SELECT id, product_name, url, current_price, created_at
        FROM price_tracker_entries
        WHERE user_id = ? AND (
            product_name LIKE ? OR url LIKE ?
        )
        ORDER BY created_at DESC
        LIMIT 3
    """, (user_id, f'%{query}%', f'%{query}%')).fetchall()
    
    for product in price_products:
        price = f"₹{product['current_price']}" \
                if product['current_price'] else 'Pending'
        results.append({
            'type': 'price',
            'icon': '🏷️',
            'title': product['product_name'] or product['url'],
            'subtitle': f"Current price: {price}",
            'url': '/price-tracker',
            'badge': 'Price Tracker',
            'badge_color': '#f59e0b'
        })
    
    # Search SEO Analyzer results
    seo_results = conn.execute("""
        SELECT url, seo_score, MAX(created_at) as created_at
        FROM seo_analyses
        WHERE user_id = ? AND url LIKE ?
        GROUP BY url
        ORDER BY created_at DESC
        LIMIT 3
    """, (user_id, f'%{query}%')).fetchall()
    
    for seo in seo_results:
        results.append({
            'type': 'seo',
            'icon': '📊',
            'title': seo['url'],
            'subtitle': f"SEO Score: {seo['seo_score'] or 'N/A'}",
            'url': '/seo-analyzer',
            'badge': 'SEO Analyzer',
            'badge_color': '#8b5cf6'
        })
    
    conn.close()
    return jsonify(results)


@auth_bp.route('/api/dashboard/activity')
@login_required
def api_activity():
    """Return per-user recent activity."""
    from models import ActivityLog
    user_id = session.get('user_id')
    activities = ActivityLog.query.filter_by(user_id=user_id).order_by(ActivityLog.created_at.desc()).limit(10).all()
    items = [
        {
            'id': activity.id,
            'event_type': activity.event_type,
            'details': activity.details,
            'created_at': activity.created_at.isoformat()
        }
        for activity in activities
    ]
    return jsonify({'activities': items})
