from datetime import timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import Admin
from utils import csrf_protect, log_access, utcnow

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@csrf_protect
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.active and admin.check_password(password):
            admin.last_login = utcnow(); db.session.commit(); login_user(admin, remember=False)
            flash('Login realizado com sucesso.', 'success')
            return redirect(url_for('admin.dashboard'))
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')

@auth_bp.post('/logout')
@login_required
@csrf_protect
def logout():
    logout_user(); flash('Sessão encerrada.', 'info'); return redirect(url_for('auth.login'))
