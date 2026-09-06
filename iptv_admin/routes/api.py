from flask import Blueprint, request, jsonify
from secrets import compare_digest
from extensions import db
from models import User
from utils import log_access, utcnow

api_bp = Blueprint('api', __name__, url_prefix='/api')

def payload():
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        data = request.args.to_dict()
    return data
def user_json(user):
    return {'username': user.username, 'name': user.name, 'active': user.active, 'expires_at': user.expires_at.isoformat() if user.expires_at else None, 'days_remaining': user.days_remaining(), 'status': user.status()}
def deny(reason, message, status=401, user=None):
    if user is not None: log_access(user.id, 'ACCESS_DENIED', False, request)
    return jsonify(success=False, authorized=False, reason=reason, message=message), status

def find_authorized(data):
    username=(data.get('username') or '').strip(); password=data.get('password') or ''; token=data.get('access_token') or request.headers.get('X-Access-Token') or ''
    user=User.query.filter_by(username=username).first()
    if not user: return None, deny('invalid_credentials','Credenciais inválidas.')
    if not user.active: return None, deny('blocked','Usuário bloqueado.',403,user)
    if user.is_expired(): return None, deny('expired','Acesso expirado.',403,user)
    if not user.check_password(password): return None, deny('invalid_credentials','Credenciais inválidas.',401,user)
    if not token or not compare_digest(token, user.access_token): return None, deny('invalid_token','Token inválido.',401,user)
    return user, None

@api_bp.post('/auth')
@api_bp.post('/login')
def login_api():
    user, error=find_authorized(payload())
    if error: return error
    user.last_login=utcnow(); db.session.commit(); log_access(user.id,'TOKEN_VALIDATED',True,request)
    return jsonify(success=True, authorized=True, user=user_json(user), username=user.username, expires_at=user.expires_at.isoformat(), days_remaining=user.days_remaining())

@api_bp.post('/validate')
def validate_api(): return login_api()

@api_bp.get('/user/status')
def user_status():
    data=payload(); username=(data.get('username') or '').strip(); token=data.get('access_token') or request.headers.get('X-Access-Token') or ''
    user=User.query.filter_by(username=username).first()
    if not user: return deny('not_found','Usuário não encontrado.',404)
    if not user.active: return deny('blocked','Usuário bloqueado.',403,user)
    if user.is_expired(): return deny('expired','Acesso expirado.',403,user)
    if not compare_digest(token, user.access_token): return deny('invalid_token','Token inválido.',401,user)
    log_access(user.id,'TOKEN_VALIDATED',True,request)
    return jsonify(success=True, authorized=True, user=user_json(user))

@api_bp.post('/logout')
def logout_api(): return jsonify(success=True, message='Sessão da API encerrada.')
