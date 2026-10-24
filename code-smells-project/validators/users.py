from errors import ValidationError
from validators.common import invalid, object_payload


def credentials(data, signup=False):
    if signup and not data:
        invalid()
    object_payload(data)
    fields = ("nome", "email", "senha") if signup else ("email", "senha")
    values = [data.get(field, "") for field in fields]
    if not all(values):
        message = "Nome, email e senha são obrigatórios" if signup else "Email e senha são obrigatórios"
        raise ValidationError(message)
    if not all(isinstance(value, str) for value in values):
        invalid()
    return values
