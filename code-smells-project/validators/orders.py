from constants import ORDER_STATUSES
from errors import ValidationError
from validators.common import invalid, object_payload, positive_integer


def order_payload(data):
    if not data:
        invalid()
    object_payload(data)
    user_id, items = data.get("usuario_id"), data.get("itens", [])
    if not user_id:
        raise ValidationError("Usuario ID é obrigatório")
    if not items:
        raise ValidationError("Pedido deve ter pelo menos 1 item")
    if not positive_integer(user_id) or not isinstance(items, list):
        invalid()
    for item in items:
        if not isinstance(item, dict):
            invalid()
        if not positive_integer(item.get("produto_id")) or not positive_integer(item.get("quantidade")):
            invalid()
    return user_id, items


def status_payload(data):
    object_payload(data)
    status = data.get("status", "")
    if status not in ORDER_STATUSES:
        raise ValidationError("Status inválido")
    return status
