"""Autorização temporária recebida do painel IPTV."""

import base64
import hashlib
import hmac
import json
import time

from flask import current_app, request, redirect, session
from urllib.parse import urlencode


def _decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def consume_handoff(token):
    if not token or '.' not in token:
        return False
    encoded, supplied = token.split('.', 1)
    secret = current_app.config.get('IPTV_AUTH_SECRET', '')
    if not secret:
        return False
    expected = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    ).rstrip(b'=').decode('ascii')
    if not hmac.compare_digest(supplied, expected):
        return False
    try:
        payload = json.loads(_decode(encoded))
        if int(payload.get('exp', 0)) < int(time.time()):
            return False
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    session['iptv_user'] = {
        'id': payload.get('uid'),
        'username': payload.get('username'),
        'name': payload.get('name'),
    }
    return True


def is_authenticated():
    return bool(session.get('iptv_user'))


def is_admin_request():
    """Valida chamadas administrativas serviço-a-serviço sem criar sessão IPTV."""
    supplied = request.headers.get('X-IPTV-Admin-Secret', '')
    configured = current_app.config.get('IPTV_AUTH_SECRET', '')
    return bool(configured and supplied and hmac.compare_digest(supplied, configured))


def require_access():
    if request.args.get('auth'):
        if consume_handoff(request.args['auth']):
            clean = request.path
            if request.query_string:
                clean = request.path
            return redirect(clean)
    if is_authenticated():
        return None
    return_url = current_app.config.get('IPTV_AUTH_RETURN_URL', '')
    if not return_url:
        return redirect('/login')
    query = urlencode({'next': request.full_path})
    return redirect(f'{return_url}?{query}')
