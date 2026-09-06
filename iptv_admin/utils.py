import secrets
from functools import wraps
from flask import abort, request, session
from models import AccessLog
from extensions import db

def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']

def validate_csrf():
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        supplied = request.form.get('_csrf') or request.headers.get('X-CSRF-Token')
        if not supplied or not secrets.compare_digest(supplied, session.get('csrf_token', '')):
            abort(400, description='Token CSRF inválido ou ausente.')

def csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        validate_csrf()
        return view(*args, **kwargs)
    return wrapped

def log_access(user_id, action, success, request):
    db.session.add(AccessLog(user_id=user_id, action=action, success=success,
        ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
        user_agent=request.headers.get('User-Agent', '')[:500]))
    db.session.commit()

def utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
