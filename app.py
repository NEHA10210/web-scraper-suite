"""
Smart Web Scraper Suite — application factory.

Usage
─────
Development:
    export APP_ENV=development
    export SECRET_KEY=dev-secret
    flask --app app run --debug

Production (Gunicorn):
    export APP_ENV=production
    export SECRET_KEY=<strong-secret>
    gunicorn "app:create_app()" -w 4 -b 0.0.0.0:8000

Running the schema migration once:
    python -c "from app import create_app; create_app()"
"""

import logging

from flask import Flask, render_template, session

from config import get_config
from database import DatabaseManager, close_db, get_db   # noqa: F401
from logger import setup_logging
from models import db, init_db

logger = logging.getLogger(__name__)


# ── Application factory ────────────────────────────────────────────────────────

def create_app(config_override: dict | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_override: Optional dict of config values that overwrite the
                         environment-based config (useful in tests).

    Returns:
        A fully configured Flask application instance.
    """
    app = Flask(__name__)

    # ── Load config ────────────────────────────────────────────────────────────
    config_class = get_config()
    app.config.from_object(config_class)
    if config_override:
        app.config.update(config_override)

    config_class.ensure_directories()

    # ── Logging ────────────────────────────────────────────────────────────────
    setup_logging(config_class)
    logger.info("Starting Smart Web Scraper Suite | env=%s", app.config.get("ENV", "unknown"))

    # ── Database (SQLAlchemy for auth) ────────────────────────────────────────
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{app.config['DATABASE_PATH']}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    init_db(app)

    # ── Legacy Database ───────────────────────────────────────────────────────
    db_manager = DatabaseManager(app.config["DATABASE_PATH"])
    db_manager.init_schema()
    app.teardown_appcontext(close_db)

    # ── Session ───────────────────────────────────────────────────────────────
    app.permanent_session_lifetime = 86400  # 1 day

    # ── Blueprints ─────────────────────────────────────────────────────────────
    _register_blueprints(app)
    _register_page_routes(app)

    # ── Error handlers ─────────────────────────────────────────────────────────
    _register_error_handlers(app)

    return app


# ── Blueprint registration ─────────────────────────────────────────────────────

def _register_blueprints(app: Flask) -> None:
    """Import and register every Blueprint here — one place, zero surprises."""

    # Auth blueprint
    from auth import auth_bp
    app.register_blueprint(auth_bp)

    # Core module Blueprints
    from blueprints.price_tracker import price_tracker_bp
    from blueprints.seo_analyzer import seo_analyzer_bp
    from blueprints.data_scraper import data_scraper_bp

    app.register_blueprint(price_tracker_bp, url_prefix='/price-tracker')
    app.register_blueprint(seo_analyzer_bp)
    app.register_blueprint(data_scraper_bp)

    # Optional pro-feature Blueprints (registered only when the module exists)
    _try_register(app, "blueprints.data_scraper_pro", "data_scraper_pro_bp")

    # Debug: Print price tracker routes
    print("Price tracker routes:")
    for rule in app.url_map.iter_rules():
        if 'price' in str(rule):
            print(f"  {rule} → {rule.methods}")

    logger.debug("Blueprints registered: %s", [bp.name for bp in app.blueprints.values()])


def _try_register(app: Flask, module_path: str, blueprint_attr: str) -> None:
    """Silently skip Blueprints whose optional dependencies aren't installed."""
    try:
        import importlib
        module = importlib.import_module(module_path)
        blueprint = getattr(module, blueprint_attr)
        app.register_blueprint(blueprint)
        logger.info("Optional blueprint registered | module=%s", module_path)
    except ImportError:
        logger.debug(
            "Optional blueprint skipped (not installed) | module=%s", module_path
        )


# ── Error handlers ─────────────────────────────────────────────────────────────

def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(404)
    def not_found(error):  # noqa: ARG001
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(error):  # noqa: ARG001
        from responses import error as err_response
        return err_response("Method not allowed.", code="METHOD_NOT_ALLOWED", status=405)

    @app.errorhandler(413)
    def request_entity_too_large(error):  # noqa: ARG001
        from responses import error as err_response
        return err_response("File too large.", code="FILE_TOO_LARGE", status=413)

    @app.errorhandler(500)
    def internal_error(exc):
        logger.exception("Unhandled server error: %s", exc)
        return render_template("500.html"), 500


# ── Page routes (no business logic) ───────────────────────────────────────────
# Keeping simple page routes directly in app.py avoids creating a Blueprint
# just to return render_template().  Any route that talks to a service should
# live in its own Blueprint.

def _register_page_routes(app: Flask) -> None:
    @app.route('/')
    def landing():
        from flask import session, redirect, url_for, render_template
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        return render_template('landing.html')

    @app.route("/smart-image-scraper")
    def smart_image_scraper_page():
        return render_template("smart_image_scraper.html")

    @app.route("/dashboard")
    def dashboard():
        from auth import login_required
        import sqlite3, os
        from datetime import datetime, timedelta
        import json
        
        # Apply login_required by wrapping the function
        def protected_dashboard():
            # Generate last 7 days date list
            today = datetime.now()
            last_7_days = []
            for i in range(6, -1, -1):
                day = today - timedelta(days=i)
                last_7_days.append(day.strftime('%Y-%m-%d'))

            # Get ALL scrape jobs for this user (no date filter)
            conn = sqlite3.connect(os.path.join('data', 'scraper_suite.db'))
            conn.row_factory = sqlite3.Row
            all_jobs = conn.execute("""
                SELECT * FROM scrape_jobs 
                WHERE user_id = ?
            """, (session['user_id'],)).fetchall()

            # Print column names to terminal
            if all_jobs:
                cursor = conn.execute(
                    "SELECT * FROM scrape_jobs LIMIT 1"
                )
                cols = [d[0] for d in cursor.description]
                print("[DASHBOARD] scrape_jobs columns:", cols)
                print("[DASHBOARD] Sample row:", dict(all_jobs[0]))
            else:
                print("[DASHBOARD] No jobs found for user:", 
                      session['user_id'])

            # Build chart data
            labels = []
            successful = []
            failed = []

            for date_str in last_7_days:
                labels.append(
                    datetime.strptime(date_str, '%Y-%m-%d')
                    .strftime('%d %b')
                )
                
                day_successful = 0
                day_failed = 0
                
                for job in all_jobs:
                    job_dict = dict(job)
                    
                    # Get the date from created_at
                    # Handle multiple formats
                    created = str(job_dict.get('created_at', '') or 
                                 job_dict.get('created', '') or
                                 job_dict.get('date', '') or '')
                    
                    # Extract just the date part
                    job_date = created[:10] if created else ''
                    
                    if job_date == date_str:
                        # Check status - handle multiple column names
                        status = str(
                            job_dict.get('status', '') or
                            job_dict.get('scrape_status', '') or
                            job_dict.get('is_success', '') or
                            'completed'
                        ).lower()
                        
                        if status in ['completed', 'success', 
                                     'done', '1', 'true']:
                            day_successful += 1
                        elif status in ['failed', 'error', 
                                       'fail', '0', 'false']:
                            day_failed += 1
                        else:
                            # Default: count as successful
                            day_successful += 1
                
                successful.append(day_successful)
                failed.append(day_failed)

            print("[DASHBOARD] Labels:", labels)
            print("[DASHBOARD] Successful:", successful)
            print("[DASHBOARD] Failed:", failed)

            chart_json = json.dumps({
                'labels': labels,
                'successful': successful,
                'failed': failed
            })
            
            conn.close()
            
            return render_template("dashboard.html", 
                                 active_page='dashboard',
                                 chart_data=chart_json)
        return login_required(protected_dashboard)()


# ── Entrypoint (dev only) ──────────────────────────────────────────────────────

if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True, host="0.0.0.0", port=5000)