import math

from errors import ValidationError


def invalid():
    raise ValidationError("Dados inválidos")


def object_payload(data):
    if not isinstance(data, dict):
        invalid()
    return data


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def positive_integer(value):
    return type(value) is int and value > 0
