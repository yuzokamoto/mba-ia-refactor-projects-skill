"""Regras de tarefas; não conhece objetos ou códigos HTTP."""
from constants import DEFAULT_PRIORITY, VALID_STATUSES
from errors import NotFoundError
from models import category as category_model, task as task_model, user as user_model
from models import persistence
from utils.clock import utc_now
from utils.formatting import percentage
from validators import task_validator


def require_task(task_id):
    task = task_model.get(task_id)
    if task is None:
        raise NotFoundError('Task não encontrada')
    return task


def list_tasks():
    result = []
    for task in task_model.list_with_relations():
        data = task.to_dict()
        data.update(overdue=task.is_overdue(),
                    user_name=task.user.name if task.user_id and task.user else None,
                    category_name=task.category.name if task.category_id and task.category else None)
        result.append(data)
    return result


def get_task(task_id):
    task = require_task(task_id)
    return dict(task.to_dict(), overdue=task.is_overdue())


def check_references(data):
    for field, model, message in (
        ('user_id', user_model, 'Usuário não encontrado'),
        ('category_id', category_model, 'Categoria não encontrada'),
    ):
        if field not in data:
            continue
        value = data[field]
        task_validator.reference_shape(value)
        if value and model.get(value) is None:
            raise NotFoundError(message)
        task_validator.reference_type(value)


def create_task(data):
    check_references(data)
    task = task_model.Task(title=data['title'], description=data.get('description', ''),
                           status=data.get('status', 'pending'),
                           priority=data.get('priority', DEFAULT_PRIORITY),
                           user_id=data.get('user_id'), category_id=data.get('category_id'),
                           due_date=data.get('due_date'), tags=data.get('tags') or None)
    with persistence.transaction('Erro ao criar task'):
        persistence.add(task)
    return task.to_dict()


def update_task(task, data):
    check_references(data)
    with persistence.transaction('Erro ao atualizar'):
        for field in ('title', 'description', 'status', 'priority', 'user_id',
                      'category_id', 'due_date', 'tags'):
            if field in data:
                setattr(task, field, data[field])
        task.updated_at = utc_now()
    return task.to_dict()


def delete_task(task_id):
    task = require_task(task_id)
    with persistence.transaction('Erro ao deletar'):
        persistence.delete(task)


def search_tasks(filters):
    return [task.to_dict() for task in task_model.search(**filters)]


def stats():
    counts = task_model.status_counts()
    total = sum(counts.values())
    done = counts.get('done', 0)
    result = {'total': total, **{status: counts.get(status, 0) for status in VALID_STATUSES}}
    result['overdue'] = task_model.count_overdue(utc_now())
    result['completion_rate'] = percentage(done, total)
    return result
