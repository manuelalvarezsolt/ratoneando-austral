from flask import Blueprint

moderator_bp = Blueprint('moderator', __name__)

from app.moderator import routes  # noqa: E402, F401
