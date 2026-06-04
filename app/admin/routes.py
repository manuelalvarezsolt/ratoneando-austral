import os
from functools import wraps
from flask import render_template, redirect, url_for, flash, abort, request, current_app
from flask_login import login_required, current_user
from app import db
from app.admin import admin_bp
from app.admin.forms import SubjectForm, UploadForm, ResourceForm
from app.models import Career, Subject, CareerSubject, Category, Resource, Contribution, SupportTicket, User, SiteConfig
from app.utils import slugify, save_uploaded_file, delete_uploaded_file


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _unique_subject_slug(name, exclude_id=None):
    base = slugify(name)
    candidate = base
    n = 2
    while True:
        existing = Subject.query.filter_by(slug=candidate).first()
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f'{base}-{n}'
        n += 1


def _apply_career_placements(subject):
    """
    Lee request.form y deja, para cada carrera, una asignación (año/cuatri) si
    está tildada, o ninguna si no. Devuelve la cantidad de carreras asignadas.
    """
    careers = Career.query.order_by(Career.order).all()
    assigned = 0
    for career in careers:
        enabled = request.form.get(f'career_{career.id}') == 'on'
        year_raw = request.form.get(f'year_{career.id}', '').strip()
        cuatri_raw = request.form.get(f'cuatri_{career.id}', '').strip()

        # Sacamos las asignaciones existentes de esta materia en esta carrera.
        CareerSubject.query.filter_by(career_id=career.id, subject_id=subject.id).delete()

        if enabled and year_raw:
            year = int(year_raw)
            cuatri = int(cuatri_raw) if (career.has_cuatrimestres and cuatri_raw) else None
            db.session.add(CareerSubject(
                career_id=career.id, subject_id=subject.id, year=year, cuatrimestre=cuatri
            ))
            assigned += 1
    return assigned


def _placements_for(subject):
    """{career_id: CareerSubject} con la 1ª asignación de cada carrera (para el form)."""
    out = {}
    if subject is None:
        return out
    for link in subject.career_links.all():
        out.setdefault(link.career_id, link)
    return out


def _uploads_size():
    folder = current_app.config.get('UPLOAD_FOLDER', '')
    total = 0
    if os.path.isdir(folder):
        for dirpath, _, files in os.walk(folder):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    if total >= 1 << 30:
        return f'{total / (1 << 30):.2f} GB'
    return f'{total / (1 << 20):.2f} MB'


@admin_bp.route('/')
@admin_required
def dashboard():
    recent_resources = Resource.query.order_by(Resource.created_at.desc()).limit(10).all()
    return render_template(
        'admin/dashboard.html',
        careers_count=Career.query.count(),
        subjects_count=Subject.query.count(),
        resources_count=Resource.query.count(),
        contributions_count=Contribution.query.count(),
        support_count=SupportTicket.query.count(),
        recent_resources=recent_resources,
        uploads_size=_uploads_size(),
        announcement=SiteConfig.get('announcement'),
    )


@admin_bp.route('/anuncio', methods=['POST'])
@admin_required
def save_announcement():
    text = request.form.get('announcement', '').strip()
    SiteConfig.set('announcement', text)
    db.session.commit()
    flash('Anuncio actualizado.' if text else 'Anuncio eliminado.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/materias')
@admin_required
def list_subjects():
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('admin/subjects.html', subjects=subjects)


@admin_bp.route('/materias/nueva', methods=['GET', 'POST'])
@admin_required
def new_subject():
    form = SubjectForm()
    careers = Career.query.order_by(Career.order).all()
    if form.validate_on_submit():
        name = form.name.data.strip()
        subject = Subject(
            name=name,
            slug=_unique_subject_slug(name),
            description=form.description.data,
        )
        db.session.add(subject)
        db.session.flush()
        assigned = _apply_career_placements(subject)
        if assigned == 0:
            db.session.rollback()
            flash('Asigná la materia al menos a una carrera (tildá la carrera e indicá el año).', 'danger')
            return render_template('admin/subject_form.html', form=form, title='Nueva materia',
                                   careers=careers, placements={})
        db.session.commit()
        flash(f'Materia "{name}" creada.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Nueva materia',
                           careers=careers, placements={})


@admin_bp.route('/materias/<int:subject_id>/editar', methods=['GET', 'POST'])
@admin_required
def edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    form = SubjectForm(obj=subject)
    careers = Career.query.order_by(Career.order).all()
    if form.validate_on_submit():
        subject.name = form.name.data.strip()
        subject.description = form.description.data
        assigned = _apply_career_placements(subject)
        if assigned == 0:
            db.session.rollback()
            flash('La materia debe pertenecer al menos a una carrera.', 'danger')
            return render_template('admin/subject_form.html', form=form, title='Editar materia',
                                   careers=careers, placements=_placements_for(subject))
        db.session.commit()
        flash('Materia actualizada.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Editar materia',
                           careers=careers, placements=_placements_for(subject))


@admin_bp.route('/materias/<int:subject_id>/eliminar', methods=['POST'])
@admin_required
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    name = subject.name
    db.session.delete(subject)
    db.session.commit()
    flash(f'Materia "{name}" eliminada.', 'success')
    return redirect(url_for('admin.list_subjects'))


def _subject_choices():
    choices = []
    for s in Subject.query.order_by(Subject.name).all():
        careers = ', '.join(c.short for c in s.careers)
        label = f'{s.name} ({careers})' if careers else s.name
        choices.append((s.id, label))
    return choices


@admin_bp.route('/subir/<subject_slug>/<category_slug>', methods=['GET', 'POST'])
@admin_required
def upload_to_category(subject_slug, category_slug):
    """Subida contextual: subject y category vienen de la URL (desde la página de materia)."""
    subject = Subject.query.filter_by(slug=subject_slug).first_or_404()
    category = Category.query.filter_by(subject_id=subject.id, slug=category_slug).first_or_404()
    # Exámenes es contenedor, no acepta archivos directamente
    if category.has_children:
        abort(400)

    form = UploadForm()
    if form.validate_on_submit():
        file_path = save_uploaded_file(
            form.file.data,
            subject_slug=subject.slug,
            category_slug=category.slug,
        )
        resource = Resource(
            title=form.title.data.strip(),
            description=form.description.data or None,
            file_path=file_path,
            subject_id=subject.id,
            category_id=category.id,
            uploaded_by_id=current_user.id,
        )
        db.session.add(resource)
        db.session.commit()
        flash(f'"{resource.title}" subido correctamente.', 'success')

        # Volver a la materia, usando la primera carrera que la tenga
        career = subject.primary_career
        if career:
            return redirect(url_for('main.subject_view',
                                    career_slug=career.slug,
                                    subject_slug=subject.slug))
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/upload_form.html',
                           form=form, subject=subject, category=category)


@admin_bp.route('/recursos/nuevo', methods=['GET', 'POST'])
@admin_required
def new_resource():
    """Subida genérica desde el panel admin (elige materia y categoría con selects)."""
    form = ResourceForm()
    form.subject_id.choices = _subject_choices()
    if form.validate_on_submit():
        category = Category.query.filter_by(
            subject_id=form.subject_id.data, slug=form.category.data
        ).first()
        if category is None:
            flash('Esa categoría no existe en la materia elegida (puede haber sido eliminada).', 'danger')
            return render_template('admin/resource_form.html', form=form, title='Nuevo recurso')

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
            flash('Debés subir un archivo PDF o proporcionar un link externo.', 'danger')
            return render_template('admin/resource_form.html', form=form, title='Nuevo recurso')

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
        flash(f'Recurso "{resource.title}" subido.', 'success')
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/resource_form.html', form=form, title='Nuevo recurso')


@admin_bp.route('/materias/<int:subject_id>/categoria/<int:category_id>/eliminar', methods=['POST'])
@admin_required
def delete_category(subject_id, category_id):
    category = Category.query.get_or_404(category_id)
    if category.subject_id != subject_id:
        abort(404)
    if not category.is_empty:
        flash('No se puede eliminar una categoría que tiene contenido. Vaciala primero.', 'danger')
    else:
        name = category.name
        db.session.delete(category)   # elimina también sus subcategorías (vacías)
        db.session.commit()
        flash(f'Categoría "{name}" eliminada de la materia.', 'success')
    return redirect(request.referrer or url_for('admin.list_subjects'))


@admin_bp.route('/recursos/<int:resource_id>/eliminar', methods=['POST'])
@admin_required
def delete_resource(resource_id):
    if not current_user.is_admin:
        abort(403)
    resource = Resource.query.get_or_404(resource_id)
    title = resource.title
    delete_uploaded_file(resource.file_path)
    db.session.delete(resource)
    db.session.commit()
    flash(f'"{title}" eliminado.', 'success')
    next_url = request.referrer or url_for('admin.dashboard')
    return redirect(next_url)


# ── Contribuciones de alumnos ─────────────────────────────────────────────────

@admin_bp.route('/contribuciones')
@admin_required
def list_contributions():
    contributions = Contribution.query.order_by(Contribution.created_at.asc()).all()
    return render_template('admin/contributions.html', contributions=contributions)


@admin_bp.route('/contribuciones/<int:contribution_id>/aprobar', methods=['POST'])
@admin_required
def approve_contribution(contribution_id):
    if not current_user.is_admin:
        abort(403)
    c = Contribution.query.get_or_404(contribution_id)
    resource = Resource(
        title=c.title,
        file_path=c.file_path,
        subject_id=c.subject_id,
        category_id=c.category_id,
        uploaded_by_id=c.uploaded_by_id,
    )
    db.session.add(resource)
    db.session.delete(c)
    db.session.commit()
    flash(f'"{resource.title}" aprobado y publicado.', 'success')
    return redirect(url_for('admin.list_contributions'))


@admin_bp.route('/contribuciones/<int:contribution_id>/rechazar', methods=['POST'])
@admin_required
def reject_contribution(contribution_id):
    if not current_user.is_admin:
        abort(403)
    c = Contribution.query.get_or_404(contribution_id)
    title = c.title
    delete_uploaded_file(c.file_path)
    db.session.delete(c)
    db.session.commit()
    flash(f'Contribución "{title}" rechazada y eliminada.', 'info')
    return redirect(url_for('admin.list_contributions'))


# ── Usuarios ─────────────────────────────────────────────────────────────────

@admin_bp.route('/usuarios')
@admin_required
def list_users():
    q = request.args.get('q', '').strip()
    query = User.query
    if q:
        pattern = f'%{q}%'
        query = query.filter(
            db.or_(User.name.ilike(pattern), User.email.ilike(pattern))
        )
    users = query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users, q=q)


@admin_bp.route('/usuarios/<int:user_id>/toggle-moderador', methods=['POST'])
@admin_required
def toggle_moderador(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('No se puede modificar el rol de un administrador.', 'danger')
        return redirect(url_for('admin.list_users'))
    user.is_moderator = not user.is_moderator
    db.session.commit()
    action = 'asignado' if user.is_moderator else 'removido'
    flash(f'Rol de moderador {action} a {user.name}.', 'success')
    return redirect(url_for('admin.list_users') + (f'?q={request.form.get("q", "")}' if request.form.get('q') else ''))


# ── Soporte ───────────────────────────────────────────────────────────────────

@admin_bp.route('/soporte')
@admin_required
def list_support():
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    return render_template('admin/support.html', tickets=tickets)
