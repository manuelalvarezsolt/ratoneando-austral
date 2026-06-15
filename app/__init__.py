import os
from flask import Flask, send_from_directory, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()
migrate = Migrate()
# Sin límite global por defecto; cada ruta sensible declara el suyo con @limiter.limit.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Necesitás iniciar sesión para acceder.'
login_manager.login_message_category = 'warning'


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    # Importamos los modelos para que Alembic los vea al autogenerar migraciones.
    from app import models  # noqa: F401
    migrate.init_app(app, db)

    from app.auth import auth_bp
    from app.main import main_bp
    from app.admin import admin_bp
    from app.moderator import moderator_bp
    from app.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(moderator_bp, url_prefix='/moderador')
    app.register_blueprint(api_bp, url_prefix='/api')
    # La API es JSON (auth por sesión + 401 explícito): se exime de CSRF.
    csrf.exempt(api_bp)

    @app.route('/sw.js')
    def service_worker():
        resp = send_from_directory(app.static_folder, 'sw.js')
        resp.headers['Content-Type'] = 'application/javascript'
        resp.headers['Service-Worker-Allowed'] = '/'
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.errorhandler(429)
    def ratelimit_handler(e):
        wants_json = (request.path == '/soporte'
                      or request.accept_mimetypes.best == 'application/json')
        if wants_json:
            return jsonify(ok=False, error='Demasiados intentos. Esperá un momento.'), 429
        return render_template('errors/429.html', limit=e.description), 429

    @app.context_processor
    def inject_pending_contributions():
        from flask_login import current_user
        if current_user.is_authenticated and (current_user.is_admin or current_user.is_moderator):
            from app.models import Contribution
            return {'pending_contributions': Contribution.query.count()}
        return {'pending_contributions': 0}

    return app
