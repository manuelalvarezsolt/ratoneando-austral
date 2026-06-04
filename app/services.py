"""Lógica de dominio compartida entre blueprints (admin y moderador)."""
from app import db
from app.models import Resource, Subject
from app.utils import delete_uploaded_file


def publish_contribution(contribution):
    """
    Convierte una contribución pendiente en un recurso publicado y elimina
    la contribución. Devuelve el Resource creado. Hace commit.
    """
    resource = Resource(
        title=contribution.title,
        file_path=contribution.file_path,
        subject_id=contribution.subject_id,
        category_id=contribution.category_id,
        uploaded_by_id=contribution.uploaded_by_id,
    )
    db.session.add(resource)
    db.session.delete(contribution)
    db.session.commit()
    return resource


def discard_contribution(contribution):
    """Rechaza una contribución: borra el archivo físico y el registro. Hace commit."""
    delete_uploaded_file(contribution.file_path)
    db.session.delete(contribution)
    db.session.commit()


def subject_choices():
    """Opciones (id, etiqueta) de materias para los <select> de subida."""
    choices = []
    for s in Subject.query.order_by(Subject.name).all():
        careers = ', '.join(c.short for c in s.careers)
        label = f'{s.name} ({careers})' if careers else s.name
        choices.append((s.id, label))
    return choices
