from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    videos = db.relationship('Video', backref='author', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    filename = db.Column(db.String(120), nullable=False)
    file_path = db.Column(db.String(200), nullable=True) # Local path (optional if using S3)
    s3_key = db.Column(db.String(200), nullable=True)    # S3 Key
    status = db.Column(db.String(20), default='pending') # pending, processing, completed, failed
    transcript = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Gemini Metadata
    gemini_file_uri = db.Column(db.String(200), nullable=True)
    gemini_file_name = db.Column(db.String(100), nullable=True)
    
    # Foreign Key
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    chats = db.relationship('ChatMessage', backref='video', lazy='dynamic', cascade="all, delete-orphan")

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    sender = db.Column(db.String(10), nullable=False) # 'user' or 'ai'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign Key
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
