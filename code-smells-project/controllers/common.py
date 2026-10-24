from flask import request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from errors import ValidationError


def read_json():
    try:
        return request.get_json()
    except (BadRequest, UnsupportedMediaType):
        raise ValidationError("Dados inválidos") from None
