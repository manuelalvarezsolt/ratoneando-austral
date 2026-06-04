from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer

from app import mail


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


def generate_verification_token(email):
    return _serializer().dumps(email, salt='email-verification')


def verify_token(token, max_age=86400):
    try:
        return _serializer().loads(token, salt='email-verification', max_age=max_age)
    except Exception:
        return None


def send_verification_email(user):
    token = generate_verification_token(user.email)
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    msg = Message(
        subject='Verificá tu cuenta en Ratoneando Austral',
        recipients=[user.email],
        html=f'''
        <p>Hola <strong>{user.name}</strong>,</p>
        <p>Gracias por registrarte en <strong>Ratoneando Austral</strong>.
        Para activar tu cuenta hacé clic en el siguiente link (válido por 24 horas):</p>
        <p><a href="{verify_url}" style="background:#0d6efd;color:#fff;padding:10px 20px;
        border-radius:5px;text-decoration:none;">Verificar mi cuenta</a></p>
        <p>O copiá este link en tu navegador:<br>{verify_url}</p>
        <p style="color:#888;font-size:12px;">Si no fuiste vos, ignorá este mensaje.</p>
        ''',
    )
    mail.send(msg)


def send_contribution_notification(contribution):
    admin_email = current_app.config['ADMIN_NOTIFY_EMAIL']
    review_url = url_for('admin.list_contributions', _external=True)
    msg = Message(
        subject='Nueva contribución pendiente — Ratoneando Austral',
        recipients=[admin_email],
        html=f'''
        <p>Nueva contribución recibida de <strong>{contribution.uploader.name}</strong>
        ({contribution.uploader.email}):</p>
        <ul>
          <li><strong>Título:</strong> {contribution.title}</li>
          <li><strong>Materia:</strong> {contribution.subject.name}</li>
          <li><strong>Categoría:</strong> {contribution.category.name}</li>
        </ul>
        <p><a href="{review_url}" style="background:#0d6efd;color:#fff;padding:10px 20px;
        border-radius:5px;text-decoration:none;">Revisar contribuciones pendientes</a></p>
        ''',
    )
    mail.send(msg)
