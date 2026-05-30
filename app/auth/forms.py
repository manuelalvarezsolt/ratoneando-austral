from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    email = StringField('Email Austral', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    remember = BooleanField('Recordarme')
    submit = SubmitField('Ingresar')


class RegisterForm(FlaskForm):
    name = StringField('Nombre completo', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email Austral', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        'Confirmar contraseña',
        validators=[DataRequired(), EqualTo('password', message='Las contraseñas no coinciden.')]
    )
    submit = SubmitField('Registrarse')
