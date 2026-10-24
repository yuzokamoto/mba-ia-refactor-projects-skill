"""Regras e operações de categorias."""
from constants import DEFAULT_COLOR
from errors import NotFoundError
from models import category as category_model, persistence


def require_category(category_id):
    category = category_model.get(category_id)
    if category is None:
        raise NotFoundError('Categoria não encontrada')
    return category


def list_categories():
    return [dict(category.to_dict(), task_count=task_count)
            for category, task_count in category_model.list_with_task_counts()]


def create_category(data):
    category = category_model.Category(name=data['name'], description=data.get('description', ''),
                                       color=data.get('color', DEFAULT_COLOR))
    with persistence.transaction('Erro ao criar categoria'):
        persistence.add(category)
    return category.to_dict()


def update_category(category, data):
    with persistence.transaction('Erro ao atualizar'):
        for field in ('name', 'description', 'color'):
            if field in data:
                setattr(category, field, data[field])
    return category.to_dict()


def delete_category(category_id):
    category = require_category(category_id)
    with persistence.transaction('Erro ao deletar'):
        persistence.delete(category)
