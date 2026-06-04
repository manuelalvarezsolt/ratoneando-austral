import re
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import event
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_moderator = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    is_verified = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    uploaded_resources = db.relationship('Resource', backref='uploader', lazy='dynamic')

    @property
    def is_frequent_contributor(self):
        return self.uploaded_resources.count() >= 5

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'


class Faculty(db.Model):
    """Una facultad o escuela de la universidad."""
    __tablename__ = 'faculties'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    order = db.Column(db.Integer, default=0)

    careers = db.relationship('Career', back_populates='faculty', order_by='Career.order')

    def __repr__(self):
        return f'<Faculty {self.name}>'


class Career(db.Model):
    """Una carrera universitaria."""
    __tablename__ = 'careers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    short = db.Column(db.String(10), nullable=False)
    order = db.Column(db.Integer, default=0)
    has_cuatrimestres = db.Column(db.Boolean, default=True, nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculties.id'), nullable=True)

    faculty = db.relationship('Faculty', back_populates='careers')
    subject_links = db.relationship(
        'CareerSubject', back_populates='career',
        lazy='dynamic', cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<Career {self.name}>'


class Subject(db.Model):
    """
    Una materia canónica. Existe UNA sola vez aunque varias carreras la
    compartan. El año y el cuatrimestre NO viven acá: dependen de la carrera
    y se guardan en CareerSubject.

    Cada materia tiene una estructura FIJA de categorías (ver CATEGORY_TREE),
    que se crea automáticamente al insertarse (ver el listener de abajo).
    """
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    career_links = db.relationship(
        'CareerSubject', back_populates='subject',
        lazy='dynamic', cascade='all, delete-orphan'
    )
    categories = db.relationship(
        'Category', back_populates='subject',
        lazy='dynamic', cascade='all, delete-orphan'
    )
    resources = db.relationship(
        'Resource', backref='subject',
        lazy='dynamic', cascade='all, delete-orphan'
    )

    @property
    def careers(self):
        """Carreras (sin duplicar) a las que pertenece esta materia."""
        seen, result = set(), []
        for link in self.career_links.order_by(CareerSubject.id).all():
            if link.career_id not in seen:
                seen.add(link.career_id)
                result.append(link.career)
        return result

    @property
    def primary_career(self):
        first = self.career_links.first()
        return first.career if first else None

    @property
    def top_categories(self):
        """Categorías de primer nivel, ordenadas."""
        return (self.categories
                .filter(Category.parent_id.is_(None))
                .order_by(Category.order).all())

    def __repr__(self):
        return f'<Subject {self.name}>'


class CareerSubject(db.Model):
    """
    Asociación carrera <-> materia con el lugar que la materia ocupa en el
    plan de esa carrera (año y cuatrimestre). cuatrimestre es nullable porque
    Biomédica organiza su plan solo por año.
    """
    __tablename__ = 'career_subjects'

    id = db.Column(db.Integer, primary_key=True)
    career_id = db.Column(db.Integer, db.ForeignKey('careers.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)          # 1–5
    cuatrimestre = db.Column(db.Integer, nullable=True)   # 1, 2 o None

    career = db.relationship('Career', back_populates='subject_links')
    subject = db.relationship('Subject', back_populates='career_links')

    __table_args__ = (
        db.UniqueConstraint('career_id', 'subject_id', 'year', 'cuatrimestre',
                            name='uq_career_subject_placement'),
    )

    def __repr__(self):
        c = f'C{self.cuatrimestre}' if self.cuatrimestre else 'anual'
        return f'<CareerSubject {self.career_id}:{self.subject_id} Y{self.year} {c}>'


# ---------------------------------------------------------------------------
# Estructura FIJA de categorías por materia.
# Formato: (slug, nombre, [hijos (slug, nombre)])
# Solo las hojas (sin hijos) pueden contener recursos. "Exámenes" es contenedor.
# ---------------------------------------------------------------------------
CATEGORY_TREE = [
    ('examenes', 'Exámenes', [
        ('parciales', 'Parciales'),
        ('finales', 'Finales'),
        ('integradores', 'Integradores'),
    ]),
    ('resumenes', 'Resúmenes', []),
    ('guias', 'Guías', []),
    ('apuntes', 'Apuntes', []),
    ('otros', 'Otros', []),
]

CATEGORY_ICONS = {
    'examenes': 'bi-mortarboard',
    'parciales': 'bi-file-earmark-text',
    'finales': 'bi-file-earmark-check',
    'integradores': 'bi-file-earmark-ruled',
    'resumenes': 'bi-journal-text',
    'guias': 'bi-list-check',
    'apuntes': 'bi-pencil-square',
    'otros': 'bi-folder',
}

# Hojas que pueden recibir recursos (para el formulario de subida del admin).
LEAF_CATEGORY_CHOICES = [
    ('parciales', 'Exámenes · Parciales'),
    ('finales', 'Exámenes · Finales'),
    ('integradores', 'Exámenes · Integradores'),
    ('resumenes', 'Resúmenes'),
    ('guias', 'Guías'),
    ('apuntes', 'Apuntes'),
    ('otros', 'Otros'),
]

# Regex para extraer el año del formato "Título (2024)" al final del título.
_YEAR_IN_TITLE = re.compile(r'\((\d{4})\)\s*$')


class Category(db.Model):
    """
    Categoría de contenido dentro de una materia. Es por-materia (cada materia
    tiene su propio juego), self-referencial para soportar Exámenes -> (Parciales,
    Finales, Integradores).
    """
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(80), nullable=False)
    order = db.Column(db.Integer, default=0)

    subject = db.relationship('Subject', back_populates='categories')
    children = db.relationship(
        'Category',
        backref=db.backref('parent', remote_side=[id]),
        order_by='Category.order',
        cascade='all, delete-orphan',
    )
    resources = db.relationship(
        'Resource', back_populates='category',
        order_by='Resource.created_at.desc()',
    )

    __table_args__ = (
        db.UniqueConstraint('subject_id', 'slug', name='uq_category_subject_slug'),
    )

    @property
    def icon(self):
        return CATEGORY_ICONS.get(self.slug, 'bi-folder')

    @property
    def has_children(self):
        return len(self.children) > 0

    @property
    def total_resources(self):
        """Recursos propios + los de las subcategorías."""
        n = len(self.resources)
        for child in self.children:
            n += len(child.resources)
        return n

    @property
    def is_empty(self):
        return self.total_resources == 0

    @property
    def sorted_resources(self):
        """Recursos ordenados por año descendente (más reciente primero).
        Recursos sin año en el título van al final."""
        def _key(r):
            m = _YEAR_IN_TITLE.search(r.title)
            return -int(m.group(1)) if m else 1
        return sorted(self.resources, key=_key)

    def __repr__(self):
        return f'<Category {self.slug} of subject {self.subject_id}>'


@event.listens_for(Subject, 'after_insert')
def _create_default_categories(mapper, connection, target):
    """Crea la estructura fija de categorías para cada materia nueva."""
    table = Category.__table__
    for order, (slug, name, children) in enumerate(CATEGORY_TREE):
        result = connection.execute(
            table.insert().values(
                subject_id=target.id, parent_id=None,
                name=name, slug=slug, order=order,
            )
        )
        parent_id = result.inserted_primary_key[0]
        for corder, (cslug, cname) in enumerate(children):
            connection.execute(
                table.insert().values(
                    subject_id=target.id, parent_id=parent_id,
                    name=cname, slug=cslug, order=corder,
                )
            )


class Resource(db.Model):
    __tablename__ = 'resources'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    file_path = db.Column(db.String(300))
    external_url = db.Column(db.String(500))
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship('Category', back_populates='resources')
    comments = db.relationship('Comment', backref='resource', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def category_path(self):
        c = self.category
        if c is None:
            return ''
        if c.parent is not None:
            return f'{c.parent.name} · {c.name}'
        return c.name

    @property
    def has_file(self):
        return bool(self.file_path)

    @property
    def has_url(self):
        return bool(self.external_url)

    def __repr__(self):
        return f'<Resource {self.title}>'


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resources.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Comment by user {self.user_id} on resource {self.resource_id}>'


class Contribution(db.Model):
    """Archivo enviado por un alumno, pendiente de aprobación por el admin."""
    __tablename__ = 'contributions'

    id             = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.String(200), nullable=False)
    file_path      = db.Column(db.String(500), nullable=False)
    subject_id     = db.Column(db.Integer, db.ForeignKey('subjects.id',  ondelete='CASCADE'), nullable=False)
    category_id    = db.Column(db.Integer, db.ForeignKey('categories.id', ondelete='CASCADE'), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    subject  = db.relationship('Subject')
    category = db.relationship('Category')
    uploader = db.relationship('User')

    def __repr__(self):
        return f'<Contribution "{self.title}" by user {self.uploaded_by_id}>'


class ForumThread(db.Model):
    __tablename__ = 'forum_threads'

    id           = db.Column(db.Integer, primary_key=True)
    faculty_id   = db.Column(db.Integer, db.ForeignKey('faculties.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    content      = db.Column(db.Text, nullable=False)
    author_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    faculty = db.relationship('Faculty', backref='threads')
    author  = db.relationship('User', foreign_keys=[author_id])
    replies = db.relationship('ForumReply', back_populates='thread',
                              lazy='dynamic', cascade='all, delete-orphan')

    @property
    def reply_count(self):
        return self.replies.count()

    def __repr__(self):
        return f'<ForumThread {self.id}: {self.title[:40]}>'


class ForumReply(db.Model):
    __tablename__ = 'forum_replies'

    id           = db.Column(db.Integer, primary_key=True)
    thread_id    = db.Column(db.Integer, db.ForeignKey('forum_threads.id'), nullable=False)
    content      = db.Column(db.Text, nullable=False)
    author_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    thread = db.relationship('ForumThread', back_populates='replies')
    author = db.relationship('User', foreign_keys=[author_id])

    def __repr__(self):
        return f'<ForumReply {self.id} on thread {self.thread_id}>'


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100))
    email      = db.Column(db.String(120))
    message    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SupportTicket {self.id}>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
