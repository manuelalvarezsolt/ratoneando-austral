import os
from flask import render_template, redirect, url_for, flash, abort, request, current_app, send_from_directory, jsonify
from flask_login import login_required, current_user
from app import db
from app.main import main_bp
from app.main.forms import CommentForm, ContributionForm, ThreadForm, ReplyForm
from app.models import Faculty, Career, Subject, CareerSubject, Category, Resource, Comment, Contribution, ForumThread, ForumReply, SupportTicket
from app.utils import slugify, save_uploaded_file


YEARS = {1: '1er Año', 2: '2do Año', 3: '3er Año', 4: '4to Año', 5: '5to Año'}
CUATRIMESTRES = {1: '1° Cuatrimestre', 2: '2° Cuatrimestre'}


@main_bp.route('/')
def index():
    faculties = Faculty.query.order_by(Faculty.order).all()
    return render_template('main/index.html', faculties=faculties)


@main_bp.route('/facultad/<faculty_slug>')
def faculty_view(faculty_slug):
    faculty = Faculty.query.filter_by(slug=faculty_slug).first_or_404()
    return render_template('main/faculty.html', faculty=faculty)


@main_bp.route('/carrera/<career_slug>')
def career_view(career_slug):
    career = Career.query.filter_by(slug=career_slug).first_or_404()

    # plan: {year: {cuatri_key: [subjects]}}  (cuatri_key 0 = sin cuatrimestre)
    plan = {}
    links = (
        career.subject_links
        .join(Subject)
        .order_by(CareerSubject.year, CareerSubject.cuatrimestre, Subject.name)
        .all()
    )
    for link in links:
        plan.setdefault(link.year, {}).setdefault(link.cuatrimestre or 0, []).append(link.subject)

    return render_template(
        'main/career.html',
        career=career,
        plan=plan,
        years=YEARS,
        cuatrimestres=CUATRIMESTRES,
    )


@main_bp.route('/carrera/<career_slug>/materia/<subject_slug>')
def subject_view(career_slug, subject_slug):
    career = Career.query.filter_by(slug=career_slug).first_or_404()
    subject = Subject.query.filter_by(slug=subject_slug).first_or_404()

    link = CareerSubject.query.filter_by(career_id=career.id, subject_id=subject.id).first()
    if link is None:
        abort(404)  # esa materia no pertenece a esta carrera

    other_careers = [c for c in subject.careers if c.id != career.id]
    contrib_form = ContributionForm() if current_user.is_authenticated and not current_user.is_admin else None

    return render_template(
        'main/subject.html',
        career=career,
        subject=subject,
        link=link,
        other_careers=other_careers,
        categories=subject.top_categories,
        year_name=YEARS.get(link.year, f'Año {link.year}'),
        cuatrimestre_name=CUATRIMESTRES.get(link.cuatrimestre) if link.cuatrimestre else None,
        contrib_form=contrib_form,
    )


@main_bp.route('/recurso/<int:resource_id>/descargar')
def download_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    if not resource.has_file:
        abort(404)
    static_dir = os.path.join(current_app.root_path, 'static')
    _, ext = os.path.splitext(resource.file_path)
    download_name = slugify(resource.title) + ext
    return send_from_directory(static_dir, resource.file_path,
                               as_attachment=True, download_name=download_name)


@main_bp.route('/recurso/<int:resource_id>', methods=['GET', 'POST'])
def resource_view(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    subject = resource.subject

    # Contexto de carrera para breadcrumb (?carrera=slug, o la primera asociada).
    career = None
    career_slug = request.args.get('carrera')
    if career_slug:
        career = Career.query.filter_by(slug=career_slug).first()
    if career is None:
        career = subject.primary_career

    form = CommentForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        comment = Comment(
            content=form.content.data.strip(),
            user_id=current_user.id,
            resource_id=resource.id,
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comentario agregado.', 'success')
        return redirect(url_for('main.resource_view', resource_id=resource.id,
                                carrera=career.slug if career else None))

    comments = resource.comments.order_by(Comment.created_at.asc()).all()
    return render_template(
        'main/resource.html',
        resource=resource,
        subject=subject,
        career=career,
        form=form,
        comments=comments,
    )


@main_bp.route('/recurso/<int:resource_id>/comentario/<int:comment_id>/eliminar', methods=['POST'])
@login_required
def delete_comment(resource_id, comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(comment)
    db.session.commit()
    flash('Comentario eliminado.', 'success')
    return redirect(url_for('main.resource_view', resource_id=resource_id,
                            carrera=request.args.get('carrera')))


@main_bp.route('/contribuir/<subject_slug>/<category_slug>', methods=['GET', 'POST'])
@login_required
def contribute(subject_slug, category_slug):
    if current_user.is_admin:
        abort(403)
    subject  = Subject.query.filter_by(slug=subject_slug).first_or_404()
    category = Category.query.filter_by(subject_id=subject.id, slug=category_slug).first_or_404()
    career   = subject.primary_career

    form = ContributionForm()
    if request.method == 'GET':
        form.tipo.data = category_slug

    if form.validate_on_submit():
        # La categoría destino viene del selector tipo (puede diferir de la URL)
        target = Category.query.filter_by(
            subject_id=subject.id, slug=form.tipo.data
        ).first() or category

        file_path = save_uploaded_file(form.file.data, subject.slug, target.slug)
        db.session.add(Contribution(
            title=form.title.data.strip(),
            file_path=file_path,
            subject_id=subject.id,
            category_id=target.id,
            uploaded_by_id=current_user.id,
        ))
        db.session.commit()
        flash('¡Gracias por aportar a Ratoneando Austral! Tu archivo será revisado por un administrador.', 'success')
        if career:
            return redirect(url_for('main.subject_view',
                                    career_slug=career.slug,
                                    subject_slug=subject.slug))
        return redirect(url_for('main.index'))

    return render_template('main/contribute.html',
                           form=form, subject=subject, category=category, career=career)


# ---------------------------------------------------------------------------
# Foro
# ---------------------------------------------------------------------------

@main_bp.route('/facultad/<faculty_slug>/foro')
def forum_index(faculty_slug):
    faculty = Faculty.query.filter_by(slug=faculty_slug).first_or_404()
    threads = (ForumThread.query
               .filter_by(faculty_id=faculty.id)
               .order_by(ForumThread.created_at.desc())
               .all())
    return render_template('main/forum.html', faculty=faculty, threads=threads)


@main_bp.route('/facultad/<faculty_slug>/foro/nuevo', methods=['GET', 'POST'])
@login_required
def new_thread(faculty_slug):
    faculty = Faculty.query.filter_by(slug=faculty_slug).first_or_404()
    form = ThreadForm()
    if form.validate_on_submit():
        thread = ForumThread(
            faculty_id=faculty.id,
            title=form.title.data.strip(),
            content=form.content.data.strip(),
            author_id=current_user.id,
            is_anonymous=form.is_anonymous.data,
        )
        db.session.add(thread)
        db.session.commit()
        return redirect(url_for('main.view_thread',
                                faculty_slug=faculty_slug, thread_id=thread.id))
    return render_template('main/thread_form.html', faculty=faculty, form=form)


@main_bp.route('/facultad/<faculty_slug>/foro/<int:thread_id>', methods=['GET', 'POST'])
def view_thread(faculty_slug, thread_id):
    faculty = Faculty.query.filter_by(slug=faculty_slug).first_or_404()
    thread = ForumThread.query.filter_by(id=thread_id, faculty_id=faculty.id).first_or_404()
    form = ReplyForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        reply = ForumReply(
            thread_id=thread.id,
            content=form.content.data.strip(),
            author_id=current_user.id,
            is_anonymous=form.is_anonymous.data,
        )
        db.session.add(reply)
        db.session.commit()
        flash('Respuesta publicada.', 'success')
        return redirect(url_for('main.view_thread',
                                faculty_slug=faculty_slug, thread_id=thread_id))
    replies = thread.replies.order_by(ForumReply.created_at.asc()).all()
    return render_template('main/thread.html',
                           faculty=faculty, thread=thread, replies=replies, form=form)


@main_bp.route('/facultad/<faculty_slug>/foro/<int:thread_id>/eliminar', methods=['POST'])
@login_required
def delete_thread(faculty_slug, thread_id):
    thread = ForumThread.query.filter_by(id=thread_id).first_or_404()
    if thread.author_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(thread)
    db.session.commit()
    flash('Hilo eliminado.', 'success')
    return redirect(url_for('main.forum_index', faculty_slug=faculty_slug))


@main_bp.route('/facultad/<faculty_slug>/foro/<int:thread_id>/respuesta/<int:reply_id>/eliminar',
               methods=['POST'])
@login_required
def delete_reply(faculty_slug, thread_id, reply_id):
    reply = ForumReply.query.get_or_404(reply_id)
    if reply.author_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(reply)
    db.session.commit()
    flash('Respuesta eliminada.', 'success')
    return redirect(url_for('main.view_thread',
                            faculty_slug=faculty_slug, thread_id=thread_id))


@main_bp.route('/soporte', methods=['POST'])
def submit_support():
    message = request.form.get('message', '').strip()
    if not message:
        return jsonify({'ok': False, 'error': 'El mensaje es requerido.'}), 400
    ticket = SupportTicket(
        name=request.form.get('name', '').strip() or None,
        email=request.form.get('email', '').strip() or None,
        message=message,
    )
    db.session.add(ticket)
    db.session.commit()
    return jsonify({'ok': True})
