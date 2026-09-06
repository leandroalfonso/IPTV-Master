import os
from flask import Flask, render_template
from flask_login import current_user
from config import Config
from extensions import db, login_manager
from models import Admin
from utils import csrf_token

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    app.jinja_env.globals['csrf_token'] = csrf_token

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.api import api_bp
    from routes.app import app_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(app_bp)

    @login_manager.user_loader
    def load_user(user_id):
        if not user_id or not user_id.startswith('admin:'):
            return None
        try:
            return db.session.get(Admin, int(user_id.split(':', 1)[1]))
        except (ValueError, TypeError):
            return None

    @app.get('/')
    def home():
        from flask import redirect, url_for
        return redirect(url_for('admin.dashboard') if current_user.is_authenticated else url_for('auth.login'))

    @app.context_processor
    def inject_helpers():
        from datetime import timezone
        return {'current_admin': current_user, 'timezone': timezone}

    @app.errorhandler(400)
    def bad_request(error): return render_template('errors/400.html', error=error), 400
    @app.errorhandler(403)
    def forbidden(error): return render_template('errors/403.html'), 403
    @app.errorhandler(404)
    def not_found(error): return render_template('errors/404.html'), 404
    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    with app.app_context():
        db.create_all()
        ensure_initial_admin(app)
    return app

def ensure_initial_admin(app):
    username = app.config.get('ADMIN_USERNAME', '').strip()
    password = app.config.get('ADMIN_PASSWORD', '')
    if not username or not password:
        return
    admin = Admin.query.filter_by(username=username).first()
    if not admin:
        admin = Admin(username=username, active=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

app = create_app()

if __name__ == '__main__':
    print('Banco/tabelas prontos. Servidor iniciado.')
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
