from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SelectField, TextAreaField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length

from app.constants import UPLOAD_ALLOWED_EXTENSIONS


class CommentForm(FlaskForm):
    content = TextAreaField('Comentario', validators=[DataRequired(), Length(min=2, max=2000)])
    submit = SubmitField('Comentar')


TIPO_CHOICES = [
    ('parciales',    'Parcial'),
    ('finales',      'Final'),
    ('integradores', 'Integrador'),
    ('resumenes',    'Resumen'),
    ('guias',        'Guía'),
    ('apuntes',      'Apunte'),
    ('otros',        'Otro'),
]


class ContributionForm(FlaskForm):
    title = StringField('Título', validators=[DataRequired(), Length(min=2, max=200)])
    tipo  = SelectField('Tipo', choices=TIPO_CHOICES)
    file  = FileField('Archivo', validators=[
        FileRequired(),
        FileAllowed(UPLOAD_ALLOWED_EXTENSIONS, 'Formato no permitido.'),
    ])
    submit = SubmitField('Enviar contribución')


class ThreadForm(FlaskForm):
    title        = StringField('Título', validators=[DataRequired(), Length(min=3, max=200)])
    content      = TextAreaField('Contenido', validators=[DataRequired(), Length(min=5, max=10000)])
    is_anonymous = BooleanField('Publicar como anónimo')
    submit       = SubmitField('Publicar hilo')


class ReplyForm(FlaskForm):
    content      = TextAreaField('Respuesta', validators=[DataRequired(), Length(min=2, max=10000)])
    is_anonymous = BooleanField('Publicar como anónimo')
    submit       = SubmitField('Responder')
