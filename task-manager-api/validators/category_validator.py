from errors import ValidationError
from validators.common import object_body, text


def payload(data, create=False):
    data = object_body(data, allow_empty=not create)
    if create and not data.get('name'):
        raise ValidationError('Nome é obrigatório')
    for field in ('name', 'description', 'color'):
        if field in data:
            text(data[field], nullable=field != 'name')
    return data
