from functools import wraps
from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from app.moderator import moderator_bp
from app.admin.forms import ResourceForm
from app.models import Subject, Category, Resource, Contribution
from app.utils import save_uploaded_file
from app.services import publish_contribution, discard_contribution, subject_choices


def moderator_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not (current_user.is_moderator or current_user.is_admin):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@moderator_bp.route('/')
@moderator_required
def dashboard():
    contributions = Contribution.query.order_by(Contribution.created_at.asc()).all()
    return render_template('moderator/dashboard.html', contributions=contributions)


@moderator_bp.route('/contribuciones/<int:contribution_id>/aprobar', methods=['POST'])
@moderator_required
def approve_contribution(contribution_id):
    c = Contribution.query.get_or_404(contribution_id)
    resource = publish_contribution(c)
    flash(f'"{resource.title}" aprobado y publicado.', 'success')
    return redirect(url_for('moderator.dashboard'))


@moderator_bp.route('/contribuciones/<int:contribution_id>/rechazar', methods=['POST'])
@moderator_required
def reject_contribution(contribution_id):
    c = Contribution.query.get_or_404(contribution_id)
    title = c.title
    discard_contribution(c)
    flash(f'Contribución "{title}" rechazada y eliminada.', 'info')
    return redirect(url_for('moderator.dashboard'))


@moderator_bp.route('/subir', methods=['GET', 'POST'])
@moderator_required
def upload():
    form = ResourceForm()
    form.subject_id.choices = subject_choices()
    if form.validate_on_submit():
        category = Category.query.filter_by(
            subject_id=form.subject_id.data, slug=form.category.data
        ).first()
        if category is None:
            flash('Categoría no encontrada para esa materia.', 'danger')
            return render_template('moderator/upload.html', form=form)

        file_path = None
        external_url = form.external_url.data.strip() if form.external_url.data else None

        if form.file.data and form.file.data.filename:
            subject = Subject.query.get(form.subject_id.data)
            file_path = save_uploaded_file(
                form.file.data,
                subject_slug=subject.slug,
                category_slug=category.slug,
            )

        if not file_path and not external_url:
            flash('Debés subir un archivo o proporcionar un link externo.', 'danger')
            return render_template('moderator/upload.html', form=form)

        resource = Resource(
            title=form.title.data.strip(),
            description=form.description.data or None,
            file_path=file_path,
            external_url=external_url,
            subject_id=category.subject_id,
            category_id=category.id,
            uploaded_by_id=current_user.id,
        )
        db.session.add(resource)
        db.session.commit()
        flash(f'Recurso "{resource.title}" publicado.', 'success')
        return redirect(url_for('moderator.dashboard'))

    return render_template('moderator/upload.html', form=form)
