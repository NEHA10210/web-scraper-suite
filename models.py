"""
Database models and initialization.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'

class ScrapedData(db.Model):
    __tablename__ = 'scraped_data'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    url = db.Column(db.Text, nullable=False)
    scrape_type = db.Column(db.String(20), nullable=False)  # text, images, both
    use_dynamic = db.Column(db.Boolean, default=False)
    result_json = db.Column(db.Text, nullable=False)  # JSON string of result
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('scraped_data', lazy=True))

    def __repr__(self):
        return f'<ScrapedData {self.id} by User {self.user_id}>'


class PriceTrackerEntry(db.Model):
    __tablename__ = 'price_tracker_entries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_name = db.Column(db.String(200))
    url = db.Column(db.Text, nullable=False)
    css_selector = db.Column(db.Text)
    current_price = db.Column(db.Float)
    lowest_price = db.Column(db.Float)
    highest_price = db.Column(db.Float)
    change_percent = db.Column(db.Float)
    frequency = db.Column(db.String(20), default='daily')
    last_checked = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('price_tracker_entries', lazy=True))

class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('price_tracker_entries.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('PriceTrackerEntry', backref=db.backref('price_history', lazy=True))


class SEOAnalysis(db.Model):
    __tablename__ = 'seo_analyses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    url = db.Column(db.Text, nullable=False)
    
    # Original database columns
    title = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    seo_score = db.Column(db.Integer, nullable=True)
    word_count = db.Column(db.Integer, nullable=True)
    heading_structure = db.Column(db.Text, nullable=True)
    link_analysis = db.Column(db.Text, nullable=True)
    image_analysis = db.Column(db.Text, nullable=True)
    technical_analysis = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    analysis_date = db.Column(db.DateTime, nullable=True)
    
    # New columns added by migration
    overall_score = db.Column(db.Integer, nullable=True)
    title_length = db.Column(db.Integer, nullable=True)
    meta_desc = db.Column(db.Text, nullable=True)
    meta_desc_length = db.Column(db.Integer, nullable=True)
    h1_count = db.Column(db.Integer, nullable=True)
    h2_count = db.Column(db.Integer, nullable=True)
    h3_count = db.Column(db.Integer, nullable=True)
    images_total = db.Column(db.Integer, nullable=True)
    images_no_alt = db.Column(db.Integer, nullable=True)
    internal_links = db.Column(db.Integer, nullable=True)
    external_links = db.Column(db.Integer, nullable=True)
    has_canonical = db.Column(db.Integer, default=0)
    has_robots_meta = db.Column(db.Integer, default=0)
    has_og_tags = db.Column(db.Integer, default=0)
    page_size_kb = db.Column(db.Float, nullable=True)
    load_time_ms = db.Column(db.Integer, nullable=True)
    issues = db.Column(db.Text, nullable=True)
    data_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('seo_analyses', lazy=True))


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  # scrape, seo, price, export, etc.
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('activity_logs', lazy=True))

def init_db(app):
    """Initialize database with tables."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        print("Database initialized and tables created.")
