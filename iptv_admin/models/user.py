import secrets
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    access_token = db.Column(db.String(128), unique=True, nullable=False, index=True, default=lambda: secrets.token_urlsafe(32))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    activated_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))
    last_login = db.Column(db.DateTime(timezone=True))
    device_limit = db.Column(db.Integer, default=99, nullable=False)
    notes = db.Column(db.Text)

    logs = db.relationship('AccessLog', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def regenerate_token(self): self.access_token = secrets.token_urlsafe(32)
    def days_remaining(self, now=None):
        if not self.expires_at: return 0
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        from math import ceil
        return max(0, ceil((expires - now).total_seconds() / 86400))
    def is_expired(self, now=None):
        if not self.expires_at: return True
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now >= expires
    def status(self, now=None):
        if not self.active: return 'blocked'
        remaining = self.days_remaining(now)
        if self.is_expired(now): return 'expired'
        return 'expiring' if remaining <= 7 else 'active'

class UserDevice(db.Model):
    __tablename__ = 'user_devices'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    device_id = db.Column(db.String(255), nullable=False)
    device_name = db.Column(db.String(160))
    ip_address = db.Column(db.String(64))
    last_seen = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

class AccessLog(db.Model):
    __tablename__ = 'access_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    user = db.relationship('User', back_populates='logs')
