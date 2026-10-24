"""Operações de usuários e migração de senhas após autenticação válida."""
from errors import ConflictError, CredentialsError, InactiveUserError, NotFoundError
from models import persistence, task as task_model, user as user_model
from validators import user_validator
from validators.common import text


def require_user(user_id):
    user = user_model.get(user_id)
    if user is None:
        raise NotFoundError('Usuário não encontrado')
    return user


def list_users():
    return [dict(user.to_dict(), task_count=task_count)
            for user, task_count in user_model.list_with_task_counts()]


def get_user(user_id):
    user = require_user(user_id)
    return dict(user.to_dict(), tasks=[task.to_dict() for task in task_model.for_user(user_id)])


def create_user(data):
    user_validator.create_fields(data)
    if user_model.find_by_email(data['email']):
        raise ConflictError('Email já cadastrado')
    role = data.get('role', 'user')
    user_validator.role(role)
    user_validator.public_fields(data)
    user = user_model.User(name=data['name'], email=data['email'], role=role)
    user.set_password(data['password'])
    with persistence.transaction('Erro ao criar usuário'):
        persistence.add(user)
    return user.to_dict()


def update_user(user, data):
    if 'email' in data:
        user_validator.email(data['email'])
        existing = user_model.find_by_email(data['email'])
        if existing and existing.id != user.id:
            raise ConflictError('Email já cadastrado')
    if 'password' in data:
        user_validator.password(data['password'])
    if 'role' in data:
        user_validator.role(data['role'])
    user_validator.public_fields(data)
    with persistence.transaction('Erro ao atualizar'):
        for field in ('name', 'email', 'role', 'active'):
            if field in data:
                setattr(user, field, data[field])
        if 'password' in data:
            user.set_password(data['password'])
    return user.to_dict()


def delete_user(user_id):
    user = require_user(user_id)
    with persistence.transaction('Erro ao deletar'):
        for task in task_model.for_user(user_id):
            persistence.delete(task)
        persistence.delete(user)


def user_tasks(user_id):
    require_user(user_id)
    result = []
    fields = ('id', 'title', 'description', 'status', 'priority', 'created_at', 'due_date')
    for task in task_model.for_user(user_id):
        base = task.to_dict()
        result.append({**{field: base[field] for field in fields}, 'overdue': task.is_overdue()})
    return result


def login(data):
    user = user_model.find_by_email(data['email'])
    if user is None:
        raise CredentialsError('Credenciais inválidas')
    text(data['email'])
    text(data['password'])
    if not user.check_password(data['password']):
        raise CredentialsError('Credenciais inválidas')
    if not user.active:
        raise InactiveUserError('Usuário inativo')
    if user.has_legacy_password():
        with persistence.transaction('Erro interno'):
            user.set_password(data['password'])
    return {'message': 'Login realizado com sucesso', 'user': user.to_dict()}
