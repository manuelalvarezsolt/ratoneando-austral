import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-prod')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(BASE_DIR, "ratoneando.db")}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    # Importada desde app.constants para mantener una sola fuente de verdad.
    from app.constants import UPLOAD_ALLOWED_EXTENSIONS
    ALLOWED_EXTENSIONS = set(UPLOAD_ALLOWED_EXTENSIONS)
    AUSTRAL_DOMAINS = ('austral.edu.ar', 'mail.austral.edu.ar')

    # Sesión base: permanente para que sobreviva al cierre del browser en la PWA,
    # pero corta (12 h) para no dejar sesiones abiertas en PCs compartidas de facultad.
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    # Remember-me cookie: solo se activa si el usuario marca "Recordarme".
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    # Rate limiting (Flask-Limiter). 'memory://' sirve para 1 proceso;
    # para varios workers usar Redis: RATELIMIT_STORAGE_URI=redis://localhost:6379
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    ADMIN_NOTIFY_EMAIL = os.environ.get('ADMIN_NOTIFY_EMAIL', 'manuelalvarezsolt@gmail.com')
