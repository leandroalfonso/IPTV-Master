from datetime import timedelta
from functools import wraps
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, desc
from extensions import db
from models import User, UserDevice, AccessLog
from utils import csrf_protect, log_access, utcnow

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.active: abort(403)
        return view(*args, **kwargs)
    return wrapped

def user_or_404(user_id):
    user = db.session.get(User, user_id)
    if not user: abort(404)
    return user

def parse_days(value, required=False):
    try:
        days = int(value)
        if days < 0 or days > 3650: raise ValueError
        return days
    except (ValueError, TypeError):
        if required: raise ValueError
        return 0

def parse_device_limit(value):
    # O limite de dispositivos foi desativado (qualquer device pode entrar).
    # Mantemos o campo no formulário apenas para compatibilidade, mas ele não
    # bloqueia mais nenhum login. Retornamos um valor alto ocioso.
    try:
        return max(1, min(100, int(value)))
    except (ValueError, TypeError):
        return 99

def status_counts(users):
    counts = {'active': 0, 'expiring': 0, 'expired': 0, 'blocked': 0}
    for u in users: counts[u.status()] += 1
    return counts

@admin_bp.get('/')
@admin_bp.get('')
@admin_required
def root(): return redirect(url_for('admin.dashboard'))

@admin_bp.get('/dashboard')
@admin_required
def dashboard():
    users = User.query.all(); counts = status_counts(users)
    recent = User.query.order_by(desc(User.created_at)).limit(8).all()
    expiring = sorted([u for u in users if u.status() == 'expiring'], key=lambda u: u.expires_at or utcnow())[:8]
    return render_template('admin/dashboard.html', counts=counts, total=len(users), recent=recent, expiring=expiring)

@admin_bp.get('/usuarios')
@admin_required
def usuarios():
    q = request.args.get('q', '').strip(); status = request.args.get('status', ''); sort = request.args.get('sort', 'created')
    query = User.query
    if q: query = query.filter(or_(User.username.ilike(f'%{q}%'), User.name.ilike(f'%{q}%'), User.email.ilike(f'%{q}%')))
    users = query.all()
    if status in {'active','expiring','expired','blocked'}: users = [u for u in users if u.status() == status]
    if sort == 'username': users.sort(key=lambda u: u.username.lower())
    elif sort == 'name': users.sort(key=lambda u: u.name.lower())
    elif sort == 'expires': users.sort(key=lambda u: u.expires_at or utcnow())
    else: users.sort(key=lambda u: u.created_at or utcnow(), reverse=True)
    try: page = max(1, int(request.args.get('page', 1)))
    except ValueError: page = 1
    per_page = 25; total = len(users); pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages); users = users[(page - 1) * per_page:page * per_page]
    return render_template('admin/usuarios.html', users=users, q=q, status=status, sort=sort, page=page, pages=pages, total=total)

@admin_bp.route('/usuarios/novo', methods=['GET','POST'])
@admin_required
@csrf_protect
def novo_usuario():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        name = request.form.get('name','').strip()
        password = request.form.get('password','')
        email = request.form.get('email','').strip() or None
        try: days = parse_days(request.form.get('days'), required=True)
        except ValueError: flash('Informe uma quantidade de dias válida entre 0 e 3650.', 'danger'); return render_template('admin/usuario_form.html', user=None)
        if not username or len(username) < 3 or not name or len(password) < 8:
            flash('Nome, usuário e senha (mínimo 8 caracteres) são obrigatórios.', 'danger'); return render_template('admin/usuario_form.html', user=None)
        if User.query.filter_by(username=username).first() or (email and User.query.filter_by(email=email).first()):
            flash('Usuário ou e-mail já cadastrado.', 'danger'); return render_template('admin/usuario_form.html', user=None)
        now = utcnow(); user = User(username=username, name=name, email=email, active='active' in request.form, activated_at=now, expires_at=now+timedelta(days=days), device_limit=parse_device_limit(request.form.get('device_limit')), notes=request.form.get('notes','').strip())
        user.set_password(password); db.session.add(user); db.session.flush(); log_access(user.id, 'USER_CREATED', True, request); db.session.commit()
        flash(f'Usuário {user.username} criado. Token: {user.access_token}', 'success')
        return redirect(url_for('admin.usuario_detalhes', user_id=user.id))
    return render_template('admin/usuario_form.html', user=None)

@admin_bp.post('/usuarios/teste')
@admin_required
@csrf_protect
def criar_usuario_teste():
    username = None
    for _ in range(10):
        candidate = f'teste-{secrets.token_hex(4)}'
        if not User.query.filter_by(username=candidate).first():
            username = candidate
            break
    if username is None:
        flash('Não foi possível gerar um usuário teste único.', 'danger')
        return redirect(url_for('admin.usuarios'))

    password = secrets.token_urlsafe(12)
    now = utcnow()
    user = User(
        username=username,
        name='Usuário teste',
        active=True,
        activated_at=now,
        expires_at=now + timedelta(hours=8),
        device_limit=99,
        notes='Usuário teste criado pelo painel; validade de 8 horas.',
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    log_access(user.id, 'TEST_USER_CREATED', True, request)
    db.session.commit()
    flash(f'Usuário teste criado. Login: {username} · Senha: {password}', 'success')
    return redirect(url_for('admin.usuario_detalhes', user_id=user.id))

@admin_bp.route('/usuarios/<int:user_id>/editar', methods=['GET','POST'])
@admin_required
@csrf_protect
def editar_usuario(user_id):
    user = user_or_404(user_id)
    if request.method == 'POST':
        username = request.form.get('username','').strip(); email = request.form.get('email','').strip() or None
        duplicate = User.query.filter(User.id != user.id, User.username == username).first()
        if email and not duplicate:
            duplicate = User.query.filter(User.id != user.id, User.email == email).first()
        if not username or not request.form.get('name','').strip() or duplicate:
            flash('Dados inválidos ou usuário/e-mail já utilizado.', 'danger'); return render_template('admin/usuario_form.html', user=user)
        user.username=username; user.name=request.form.get('name').strip(); user.email=email; user.device_limit=parse_device_limit(request.form.get('device_limit')); user.notes=request.form.get('notes','').strip(); user.active='active' in request.form
        if request.form.get('password'): user.set_password(request.form['password'])
        db.session.commit(); flash('Usuário atualizado.', 'success'); return redirect(url_for('admin.usuario_detalhes', user_id=user.id))
    return render_template('admin/usuario_form.html', user=user)

@admin_bp.get('/usuarios/<int:user_id>')
@admin_required
def usuario_detalhes(user_id):
    user=user_or_404(user_id); logs=AccessLog.query.filter_by(user_id=user.id).order_by(desc(AccessLog.created_at)).limit(20).all()
    return render_template('admin/usuario_detalhes.html', user=user, logs=logs)

@admin_bp.post('/usuarios/<int:user_id>/renovar')
@admin_required
@csrf_protect
def renovar(user_id):
    user=user_or_404(user_id)
    try: days=parse_days(request.form.get('days'), required=True)
    except ValueError: flash('Quantidade de dias inválida.', 'danger'); return redirect(request.referrer or url_for('admin.usuarios'))
    now=utcnow(); current=user.expires_at
    if not current or user.is_expired(now): user.expires_at=now+timedelta(days=days)
    else: user.expires_at=current+timedelta(days=days)
    user.active=True; user.activated_at=user.activated_at or now; db.session.flush(); log_access(user.id,'USER_RENEWED',True,request); db.session.commit(); flash(f'Acesso renovado por {days} dias.', 'success'); return redirect(request.referrer or url_for('admin.usuarios'))

@admin_bp.post('/usuarios/<int:user_id>/toggle')
@admin_required
@csrf_protect
def toggle(user_id):
    user=user_or_404(user_id); user.active=not user.active; db.session.flush(); log_access(user.id, 'USER_UNBLOCKED' if user.active else 'USER_BLOCKED', True, request); db.session.commit(); flash('Usuário ativado.' if user.active else 'Usuário bloqueado.', 'success'); return redirect(request.referrer or url_for('admin.usuarios'))

@admin_bp.post('/usuarios/<int:user_id>/token')
@admin_required
@csrf_protect
def token(user_id):
    user=user_or_404(user_id); user.regenerate_token(); db.session.flush(); log_access(user.id,'TOKEN_REGENERATED',True,request); db.session.commit(); flash(f'Novo token: {user.access_token}', 'success'); return redirect(url_for('admin.usuario_detalhes', user_id=user.id))

@admin_bp.post('/usuarios/<int:user_id>/reset-senha')
@admin_required
@csrf_protect
def reset_senha(user_id):
    user=user_or_404(user_id); password=request.form.get('password','')
    if len(password)<8: flash('A nova senha precisa ter ao menos 8 caracteres.', 'danger')
    else: user.set_password(password); db.session.commit(); flash('Senha redefinida.', 'success')
    return redirect(url_for('admin.usuario_detalhes', user_id=user.id))

@admin_bp.post('/usuarios/<int:user_id>/excluir')
@admin_required
@csrf_protect
def excluir(user_id):
    user=user_or_404(user_id); db.session.delete(user); db.session.commit(); flash('Usuário excluído.', 'success'); return redirect(url_for('admin.usuarios'))

@admin_bp.get('/usuarios/<int:user_id>/dispositivos')
@admin_required
def dispositivos(user_id):
    user=user_or_404(user_id)
    devices=UserDevice.query.filter_by(user_id=user.id).order_by(desc(UserDevice.last_seen)).all()
    return render_template('admin/dispositivos.html', user=user, devices=devices)

@admin_bp.post('/usuarios/<int:user_id>/dispositivos/revogar')
@admin_required
@csrf_protect
def revogar_dispositivo(user_id):
    user=user_or_404(user_id)
    device_id=(request.form.get('device_id') or '').strip()
    if not device_id:
        flash('Dispositivo não informado.', 'danger'); return redirect(url_for('admin.dispositivos', user_id=user.id))
    device=UserDevice.query.filter_by(user_id=user.id, device_id=device_id).first()
    if device:
        device.active=False; db.session.commit(); log_access(user.id, 'DEVICE_REVOKED', True, request)
        flash('Dispositivo encerrado.', 'success')
    else:
        flash('Dispositivo não encontrado.', 'warning')
    return redirect(url_for('admin.dispositivos', user_id=user.id))

@admin_bp.post('/usuarios/<int:user_id>/dispositivos/revogar-todos')
@admin_required
@csrf_protect
def revogar_todos_dispositivos(user_id):
    user=user_or_404(user_id)
    count=UserDevice.query.filter_by(user_id=user.id, active=True).update({'active': False})
    db.session.commit(); log_access(user.id, 'DEVICE_REVOKED_ALL', True, request)
    flash(f'{count} dispositivo(s) encerrado(s).', 'success')
    return redirect(url_for('admin.dispositivos', user_id=user.id))

def _streamvault_config(action=None, payload=None):
    base_url = current_app.config.get('IPTV_APP_URL', '').rstrip('/')
    secret = current_app.config.get('IPTV_AUTH_SECRET', '')
    if not base_url or not secret:
        return None, 'Integração com o StreamVault não configurada.'
    body = dict(payload or {})
    if action:
        body['action'] = action
    method = 'POST' if body else 'GET'
    headers = {'X-IPTV-Admin-Secret': secret}
    data = json.dumps(body).encode() if body else None
    if data:
        headers['Content-Type'] = 'application/json'
    try:
        response = urlopen(Request(f'{base_url}/api/admin/config', data=data, headers=headers, method=method), timeout=30)
        return json.loads(response.read().decode()), None
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return None, f'Não foi possível comunicar com o StreamVault ({type(exc).__name__}).'


@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@admin_required
@csrf_protect
def configuracoes():
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action in {'save', 'validate'}:
            source = request.form.get('IPTV_M3U_URL', '').strip()
            payload = {
                'IPTV_M3U_URL': source,
                'IPTV_TYPE': 'm3u',
                'IPTV_CACHE_MINUTES': request.form.get('IPTV_CACHE_MINUTES', '30'),
            }
            if action == 'validate':
                payload['action'] = 'validate'
            result, error = _streamvault_config(payload=payload)
        else:
            result, error = _streamvault_config(action=action)
        if error:
            flash(error, 'danger')
        elif action == 'validate' and result and result.get('ok'):
            flash(f"Fonte válida: {result.get('total', 0)} itens — {result.get('channels', 0)} canais, {result.get('movies', 0)} filmes e {result.get('series', 0)} séries.", 'success')
        elif result and result.get('ok'):
            if action == 'rollback':
                flash('Configuração anterior restaurada.', 'success')
            elif action == 'refresh':
                flash(f"Lista atualizada: {result.get('total', 0)} itens carregados.", 'success')
            else:
                flash('Configuração da lista IPTV atualizada.', 'success')
        else:
            flash((result or {}).get('error', 'Operação não concluída.'), 'danger')
        return redirect(url_for('admin.configuracoes'))

    status, error = _streamvault_config()
    return render_template('admin/configuracoes.html', status=status or {}, integration_error=error)
