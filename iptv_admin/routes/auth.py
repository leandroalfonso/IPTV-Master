from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import Admin, User
from utils import csrf_protect, log_access, utcnow

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@csrf_protect
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        # 1) Conta de ADMIN -> painel administrativo
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.active and admin.check_password(password):
            admin.last_login = utcnow(); db.session.commit(); login_user(admin, remember=False)
            return redirect(url_for('admin.dashboard'))
        # 2) Conta de USUÁRIO -> app de filmes (handoff)
        user = User.query.filter_by(username=username).first()
        if user and user.active and not user.is_expired():
            if user.check_password(password):
                from routes.app import _handoff_token, _iptv_url
                token = _handoff_token(user)
                target = _iptv_url(user)
                if token and target:
                    log_access(user.id, 'LOGIN', True, request)
                    return redirect(target)
                error = 'Não foi possível gerar o acesso ao app.'
            else:
                error = 'Usuário ou senha inválidos.'
        elif user:
            error = 'Usuário bloqueado ou expirado.'
        else:
            error = 'Usuário ou senha inválidos.'
        return render_template('auth/login.html', error=error), 401
    return render_template('auth/login.html', error=error)

@auth_bp.post('/logout')
@login_required
@csrf_protect
def logout():
    logout_user(); flash('Sessão encerrada.', 'info'); return redirect(url_for('auth.login'))
