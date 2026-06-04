from markupsafe import Markup
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.auth import auth_bp
from app.auth.forms import LoginForm, RegisterForm
from app.models import User
from app.utils import is_austral_email
from app.email import send_verification_email, verify_token


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            if not user.is_verified:
                resend_url = url_for('auth.resend_verification', email=user.email)
                flash(
                    Markup(
                        f'Verificá tu email antes de ingresar. '
                        f'¿No llegó el mail? <a href="{resend_url}">Reenviar verificación</a>.'
                    ),
                    'warning',
                )
                return render_template('auth/login.html', form=form)
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        flash('Email o contraseña incorrectos.', 'danger')
    return render_template('auth/login.html', form=form)


@auth_bp.route('/registro', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        if not is_austral_email(email):
            flash('Solo se puede registrar con un email de la Universidad Austral (@austral.edu.ar o @mail.austral.edu.ar).', 'danger')
            return render_template('auth/register.html', form=form)
        if User.query.filter_by(email=email).first():
            flash('Ya existe una cuenta con ese email.', 'danger')
            return render_template('auth/register.html', form=form)
        user = User(name=form.name.data.strip(), email=email, is_verified=True)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('¡Cuenta creada! Ya podés ingresar.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)


@auth_bp.route('/verificar/<token>')
def verify_email(token):
    email = verify_token(token)
    if email is None:
        flash('El link de verificación es inválido o expiró. Pedí uno nuevo.', 'danger')
        return redirect(url_for('auth.login'))
    user = User.query.filter_by(email=email).first()
    if user is None:
        flash('No se encontró la cuenta.', 'danger')
        return redirect(url_for('auth.login'))
    if user.is_verified:
        flash('Tu cuenta ya está verificada. Podés ingresar.', 'info')
        return redirect(url_for('auth.login'))
    user.is_verified = True
    db.session.commit()
    flash('¡Cuenta verificada! Ya podés ingresar.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reenviar-verificacion')
def resend_verification():
    email = request.args.get('email', '').lower().strip()
    if not email:
        flash('Falta el email.', 'danger')
        return redirect(url_for('auth.login'))
    user = User.query.filter_by(email=email).first()
    if user and not user.is_verified:
        try:
            send_verification_email(user)
        except Exception:
            flash('No se pudo enviar el email. Intentá de nuevo más tarde.', 'danger')
            return redirect(url_for('auth.login'))
    # Respuesta genérica para no exponer si el email existe
    flash('Si el email está registrado y sin verificar, te enviamos un nuevo link.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
