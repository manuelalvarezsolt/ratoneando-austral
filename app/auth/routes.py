from urllib.parse import urlparse, urljoin
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db, limiter
from app.auth import auth_bp
from app.auth.forms import LoginForm, RegisterForm
from app.models import User
from app.utils import is_austral_email


def _safe_next(target):
    """
    Devuelve `target` solo si es un destino local seguro; si no, None.
    Evita open redirects: rechaza URLs absolutas, protocol-relative (//host)
    y cualquier cosa que apunte fuera del host actual.
    """
    if not target:
        return None
    # Rechazo temprano de trucos comunes (//evil, /\evil, http:evil).
    if target.startswith('//') or '\\' in target or '://' in target:
        return None
    test = urlparse(urljoin(request.host_url, target))
    if test.scheme in ('http', 'https') and test.netloc == urlparse(request.host_url).netloc:
        return target
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('8 per minute; 40 per hour', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = _safe_next(request.args.get('next'))
            return redirect(next_page or url_for('main.index'))
        flash('Email o contraseña incorrectos.', 'danger')
    return render_template('auth/login.html', form=form)


@auth_bp.route('/registro', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
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



@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
