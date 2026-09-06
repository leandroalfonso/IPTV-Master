import base64
import hashlib
import hmac
import json
import os
import time
from functools import wraps

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from extensions import db
from models import User
from utils import csrf_protect, log_access, utcnow

app_bp = Blueprint('user_app', __name__, url_prefix='/app')


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _handoff_token(user):
    secret = current_app.config.get('IPTV_AUTH_SECRET', '')
    if not secret:
        return None
    payload = {
        'uid': user.id,
        'username': user.username,
        'name': user.name,
        'exp': int(time.time()) + 60,
    }
    encoded = _b64(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f'{encoded}.{_b64(signature)}'


def _iptv_url(user):
    target = current_app.config.get('IPTV_APP_URL', '').rstrip('/')
    token = _handoff_token(user)
    if not target or not token:
        return None
    return f'{target}/?auth={token}'


def app_user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get('app_user_id')
        user = db.session.get(User, user_id) if user_id else None
        if not user:
            session.pop('app_user_id', None)
            return redirect(url_for('user_app.login'))
        if not user.active:
            session.pop('app_user_id', None)
            return render_template('app/login.html', error='Usuário bloqueado.'), 403
        if user.is_expired():
            session.pop('app_user_id', None)
            return render_template('app/login.html', error='Acesso expirado.'), 403
        return view(user, *args, **kwargs)
    return wrapped


@app_bp.route('/login', methods=['GET', 'POST'])
@csrf_protect
def login():
    if session.get('app_user_id'):
        return redirect(url_for('user_app.home'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            error = 'Usuário ou senha inválidos.'
            if user:
                log_access(user.id, 'LOGIN_FAILED', False, request)
            return render_template('app/login.html', error=error), 401
        if not user.active:
            log_access(user.id, 'ACCESS_DENIED', False, request)
            return render_template('app/login.html', error='Usuário bloqueado.'), 403
        if user.is_expired():
            log_access(user.id, 'ACCESS_DENIED', False, request)
            return render_template('app/login.html', error='Acesso expirado.'), 403
        session.clear()
        session['app_user_id'] = user.id
        user.last_login = utcnow()
        db.session.commit()
        log_access(user.id, 'LOGIN', True, request)
        target = _iptv_url(user)
        if target:
            return redirect(target)
        return redirect(url_for('user_app.home'))
    return render_template('app/login.html', error=error)


@app_bp.get('', strict_slashes=False)
@app_user_required
def home(user):
    return render_template('app/home.html', user=user)


@app_bp.post('/logout')
@csrf_protect
@app_user_required
def logout(user):
    session.pop('app_user_id', None)
    log_access(user.id, 'LOGOUT', True, request)
    return redirect(url_for('user_app.login'))
