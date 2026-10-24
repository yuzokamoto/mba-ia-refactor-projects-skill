import re
from constants import MIN_PASSWORD_LENGTH, VALID_ROLES
from errors import ValidationError
from validators.common import invalid, object_body, text

EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$')


def email(value):
    text(value)
    if not EMAIL_PATTERN.match(value):
        raise ValidationError('Email inválido')


def password(value, create=False):
    try:
        length = len(value)
    except TypeError:
        invalid()
    if length < MIN_PASSWORD_LENGTH:
        message = 'Senha deve ter no mínimo 4 caracteres' if create else 'Senha muito curta'
        raise ValidationError(message)
    text(value)


def role(value):
    if value not in VALID_ROLES:
        raise ValidationError('Role inválido')


def create_fields(data):
    for field, message in (('name', 'Nome é obrigatório'), ('email', 'Email é obrigatório'),
                           ('password', 'Senha é obrigatória')):
        if not data.get(field):
            raise ValidationError(message)
    email(data['email'])
    password(data['password'], create=True)


def public_fields(data):
    if 'name' in data:
        text(data['name'])
    if 'active' in data and type(data['active']) is not bool:
        invalid()


def login_payload(data):
    data = object_body(data)
    if not data.get('email') or not data.get('password'):
        raise ValidationError('Email e senha são obrigatórios')
    # Valores escalares inexistentes mantêm o 401 anterior à verificação da senha.
    if not isinstance(data['email'], (str, int, float, bool)):
        invalid()
    return data
