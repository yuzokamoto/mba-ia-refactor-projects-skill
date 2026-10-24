from errors import ValidationError


def invalid():
    raise ValidationError('Dados inválidos')


def object_body(data, allow_empty=False):
    if not isinstance(data, dict) or (not data and not allow_empty):
        invalid()
    return dict(data)


def text(value, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str):
        invalid()
