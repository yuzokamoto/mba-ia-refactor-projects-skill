from constants import PRODUCT_CATEGORIES, PRODUCT_NAME_MAX, PRODUCT_NAME_MIN
from errors import ValidationError
from validators.common import finite_number, invalid, object_payload


def product_payload(data, update=False):
    if not data:
        invalid()
    # Mantém a precedência das mensagens de campos ausentes já tratadas pela API.
    if isinstance(data, (dict, list, str)):
        for key, message in (("nome", "Nome é obrigatório"), ("preco", "Preço é obrigatório"),
                             ("estoque", "Estoque é obrigatório")):
            if key not in data:
                raise ValidationError(message)
    object_payload(data)
    name, price, stock = data["nome"], data["preco"], data["estoque"]
    if not finite_number(price) or type(stock) is not int:
        invalid()
    if price < 0:
        raise ValidationError("Preço não pode ser negativo")
    if stock < 0:
        raise ValidationError("Estoque não pode ser negativo")
    if isinstance(name, (str, list, dict)) and len(name) < PRODUCT_NAME_MIN:
        raise ValidationError("Dados inválidos" if update else "Nome muito curto")
    if isinstance(name, (str, list, dict)) and len(name) > PRODUCT_NAME_MAX:
        raise ValidationError("Dados inválidos" if update else "Nome muito longo")
    if not isinstance(name, str):
        invalid()
    category = data.get("categoria", "geral")
    if category not in PRODUCT_CATEGORIES:
        if update:
            invalid()
        raise ValidationError("Categoria inválida. Válidas: " + str(list(PRODUCT_CATEGORIES)))
    description = data.get("descricao", "")
    if not isinstance(description, str):
        invalid()
    return dict(nome=name, descricao=description, preco=price, estoque=stock, categoria=category)


def search_parameters(args):
    limits = []
    for key in ("preco_min", "preco_max"):
        value = args.get(key)
        if value:
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                invalid()
            if not finite_number(value):
                invalid()
        limits.append(value)
    return args.get("q", ""), args.get("categoria"), *limits
