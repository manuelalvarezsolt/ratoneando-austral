from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, SelectField, TextAreaField, SubmitField, URLField
from wtforms.validators import DataRequired, Length, Optional, URL

from app.models import LEAF_CATEGORY_CHOICES


class SubjectForm(FlaskForm):
    name = StringField('Nombre de la materia', validators=[DataRequired(), Length(min=2, max=120)])
    description = TextAreaField('Descripción (opcional)', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Guardar materia')


class UploadForm(FlaskForm):
    """Formulario de subida contextual (subject + category ya vienen de la URL)."""
    title = StringField('Título / Nombre del archivo', validators=[DataRequired(), Length(min=2, max=200)])
    description = TextAreaField('Descripción (opcional)', validators=[Optional(), Length(max=500)])
    file = FileField(
        'Archivo PDF',
        validators=[
            DataRequired(message='Seleccioná un archivo PDF.'),
            FileAllowed(['pdf'], 'Solo se permiten archivos PDF.'),
        ],
    )
    submit = SubmitField('Subir')


class ResourceForm(FlaskForm):
    """Formulario genérico desde el panel admin (sin contexto de URL)."""
    title = StringField('Título', validators=[DataRequired(), Length(min=2, max=200)])
    subject_id = SelectField('Materia', coerce=int, validators=[DataRequired()])
    category = SelectField('Categoría', choices=LEAF_CATEGORY_CHOICES, validators=[DataRequired()])
    description = TextAreaField('Descripción (opcional)', validators=[Optional(), Length(max=1000)])
    file = FileField(
        'Archivo PDF',
        validators=[
            Optional(),
            FileAllowed(['pdf'], 'Solo se permiten archivos PDF.'),
        ],
    )
    external_url = URLField('O pegá un link externo (Drive, etc.)', validators=[Optional(), URL()])
    submit = SubmitField('Subir recurso')
