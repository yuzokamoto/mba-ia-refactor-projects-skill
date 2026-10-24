from datetime import datetime
from constants import MAX_PRIORITY, MAX_TITLE_LENGTH, MIN_PRIORITY, MIN_TITLE_LENGTH, VALID_STATUSES
from errors import ValidationError
from validators.common import invalid, object_body, text


def payload(data, create=False):
    data = object_body(data)
    if create and not data.get('title'):
        raise ValidationError('Título é obrigatório')
    if 'title' in data:
        title = data['title']
        try:
            length = len(title)
        except TypeError:
            invalid()
        if length < MIN_TITLE_LENGTH:
            raise ValidationError('Título muito curto')
        if length > MAX_TITLE_LENGTH:
            raise ValidationError('Título muito longo')
        text(title)
    if 'status' in data and data['status'] not in VALID_STATUSES:
        raise ValidationError('Status inválido')
    if 'priority' in data:
        priority = data['priority']
        if isinstance(priority, (int, float)) and not MIN_PRIORITY <= priority <= MAX_PRIORITY:
            raise ValidationError('Prioridade deve ser entre 1 e 5')
        if type(priority) is not int:
            invalid()
    if 'description' in data:
        text(data['description'], nullable=True)
    if 'due_date' in data:
        due_date = data['due_date']
        if due_date:
            try:
                data['due_date'] = datetime.strptime(due_date, '%Y-%m-%d')
            except (TypeError, ValueError):
                message = ('Formato de data inválido. Use YYYY-MM-DD'
                           if create else 'Formato de data inválido')
                raise ValidationError(message) from None
        else:
            if due_date is not None and not isinstance(due_date, str):
                invalid()
            data['due_date'] = None
    if 'tags' in data:
        tags = data['tags']
        if isinstance(tags, list):
            if not all(isinstance(tag, str) for tag in tags):
                invalid()
            data['tags'] = ','.join(tags)
        elif tags is not None and not isinstance(tags, str):
            invalid()
    return data


def reference_shape(value):
    # Uma lista unitária pode ter produzido 404 no contrato antigo.
    if isinstance(value, (dict, list)) and not (isinstance(value, list) and len(value) == 1):
        invalid()


def reference_type(value):
    if value is not None and type(value) is not int:
        invalid()


def search_query(args):
    result = {'query': args.get('q', ''), 'status': args.get('status', '')}
    for field in ('priority', 'user_id'):
        value = args.get(field, '')
        if value:
            try:
                result[field] = int(value)
            except (TypeError, ValueError):
                invalid()
        else:
            result[field] = None
    return result
