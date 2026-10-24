"""Dados iniciais e repovoamento atômico."""
from datetime import timedelta
from models import category as category_model, persistence, task as task_model, user as user_model
from utils.clock import utc_now

SEED_PASSWORD_NAMES = ('SEED_ADMIN_PASSWORD', 'SEED_USER_PASSWORD', 'SEED_MANAGER_PASSWORD')


def validate_passwords(passwords):
    if any(not isinstance(passwords.get(name), str) or not passwords[name] for name in SEED_PASSWORD_NAMES):
        raise ValueError('Configure SEED_ADMIN_PASSWORD, SEED_USER_PASSWORD e SEED_MANAGER_PASSWORD antes do seed')


def populate(passwords):
    validate_passwords(passwords)
    with persistence.transaction('Erro ao popular banco'):
        task_model.clear()
        user_model.clear()
        category_model.clear()
        users = []
        for name, email, role, variable in (
            ('João Silva', 'joao@email.com', 'admin', 'SEED_ADMIN_PASSWORD'),
            ('Maria Santos', 'maria@email.com', 'user', 'SEED_USER_PASSWORD'),
            ('Pedro Oliveira', 'pedro@email.com', 'manager', 'SEED_MANAGER_PASSWORD'),
        ):
            user = user_model.User(name=name, email=email, role=role)
            user.set_password(passwords[variable])
            persistence.add(user)
            users.append(user)
        persistence.flush()
        categories = []
        for name, description, color in (
            ('Backend', 'Tarefas de backend', '#3498db'),
            ('Frontend', 'Tarefas de frontend', '#2ecc71'),
            ('DevOps', 'Tarefas de infraestrutura', '#e74c3c'),
            ('Bug', 'Correção de bugs', '#e67e22'),
        ):
            category = category_model.Category(name=name, description=description, color=color)
            persistence.add(category)
            categories.append(category)
        persistence.flush()
        tasks = task_data(users, categories)
        for data in tasks:
            persistence.add(task_model.Task(**data))
    return len(users), len(categories), len(tasks)


def task_data(users, categories):
    admin, regular, manager = users
    backend, frontend, devops, bug = categories
    return [
        {'title': 'Implementar autenticação JWT', 'description': 'Adicionar autenticação real com JWT', 'status': 'pending', 'priority': 1, 'user_id': admin.id, 'category_id': backend.id, 'due_date': utc_now() - timedelta(days=3)},
        {'title': 'Criar tela de login', 'description': 'Tela de login responsiva', 'status': 'in_progress', 'priority': 2, 'user_id': regular.id, 'category_id': frontend.id, 'due_date': utc_now() + timedelta(days=5)},
        {'title': 'Configurar CI/CD', 'description': 'Pipeline com GitHub Actions', 'status': 'done', 'priority': 2, 'user_id': manager.id, 'category_id': devops.id, 'tags': 'devops,ci,github'},
        {'title': 'Corrigir bug no filtro de busca', 'description': 'Filtro não funciona com caracteres especiais', 'status': 'pending', 'priority': 1, 'user_id': admin.id, 'category_id': bug.id, 'due_date': utc_now() - timedelta(days=1)},
        {'title': 'Adicionar paginação na API', 'description': 'Endpoints retornam todos os registros', 'status': 'pending', 'priority': 3, 'user_id': admin.id, 'category_id': backend.id, 'due_date': utc_now() + timedelta(days=10)},
        {'title': 'Escrever testes unitários', 'description': 'Cobertura mínima de 80%', 'status': 'pending', 'priority': 2, 'user_id': regular.id, 'category_id': backend.id},
        {'title': 'Documentar API com Swagger', 'description': 'Gerar documentação automática', 'status': 'cancelled', 'priority': 4, 'user_id': manager.id, 'category_id': backend.id},
        {'title': 'Refatorar models', 'description': 'Melhorar organização dos models', 'status': 'in_progress', 'priority': 3, 'user_id': regular.id, 'category_id': backend.id, 'tags': 'refactor,tech-debt'},
        {'title': 'Configurar monitoramento', 'description': 'Prometheus + Grafana', 'status': 'pending', 'priority': 4, 'user_id': manager.id, 'category_id': devops.id, 'due_date': utc_now() + timedelta(days=20)},
        {'title': 'Melhorar validações de input', 'description': 'Usar marshmallow ou pydantic', 'status': 'pending', 'priority': 3, 'user_id': admin.id, 'category_id': backend.id, 'tags': 'improvement,validation'},
    ]
