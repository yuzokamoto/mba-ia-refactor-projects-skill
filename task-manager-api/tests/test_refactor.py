"""Verificações de segurança, transações e compatibilidade do contrato."""
import hashlib
import importlib
import os
import secrets
import unittest
from unittest.mock import patch

from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash

from app import create_app
from config.settings import settings_from_environment
from database import db
from errors import PersistenceError
from models import persistence
from models.category import Category
from models.task import Task
from models.user import User
from seed import seed_data
from services.seed_service import SEED_PASSWORD_NAMES, populate

PROTECTED_ROUTES = (
    ('POST', '/tasks'), ('PUT', '/tasks/99999'), ('DELETE', '/tasks/99999'),
    ('GET', '/users'), ('GET', '/users/99999'), ('POST', '/users'),
    ('PUT', '/users/99999'), ('DELETE', '/users/99999'),
    ('GET', '/users/99999/tasks'), ('POST', '/categories'),
    ('PUT', '/categories/99999'), ('DELETE', '/categories/99999'),
    ('GET', '/reports/summary'), ('GET', '/reports/user/99999'),
)


class RefactorTests(unittest.TestCase):
    def setUp(self):
        self.admin_token = secrets.token_urlsafe(24)
        self.seed_password = secrets.token_urlsafe(16)
        self.passwords = {name: self.seed_password for name in SEED_PASSWORD_NAMES}
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'ADMIN_TOKEN': self.admin_token, 'CORS_ORIGINS': [],
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        populate(self.passwords)
        self.client = self.app.test_client()
        self.headers = {'X-Admin-Token': self.admin_token}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def snapshot(self):
        return {
            'users': [(user.id, user.name, user.email,
                       hashlib.sha256(user.password.encode()).hexdigest()) for user in
                      db.session.scalars(select(User).order_by(User.id))],
            'categories': [category.to_dict() for category in
                           db.session.scalars(select(Category).order_by(Category.id))],
            'tasks': [task.to_dict() for task in
                      db.session.scalars(select(Task).order_by(Task.id))],
        }

    def test_no_schema_creation_on_import_or_factory(self):
        import app
        with patch.object(db, 'create_all') as create_schema:
            importlib.reload(app)
            create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        create_schema.assert_not_called()

    def test_safe_defaults_without_environment_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            first = settings_from_environment()
            second = settings_from_environment()
        self.assertFalse(first['DEBUG'])
        self.assertEqual(first['HOST'], '127.0.0.1')
        self.assertEqual(first['CORS_ORIGINS'], [])
        self.assertIsNone(first['ADMIN_TOKEN'])
        self.assertNotEqual(first['SECRET_KEY'], second['SECRET_KEY'])

    def test_auth_precedes_body_validation_and_resource_lookup(self):
        for method, path in PROTECTED_ROUTES:
            for token in (None, secrets.token_urlsafe(24)):
                with self.subTest(method=method, path=path, token_present=token is not None):
                    headers = {} if token is None else {'X-Admin-Token': token}
                    response = self.client.open(path, method=method, data='{',
                                                content_type='application/json', headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json, {'error': 'Não autorizado'})

    def test_admin_routes_disabled_when_token_is_not_configured(self):
        self.app.config['ADMIN_TOKEN'] = None
        for method, path in PROTECTED_ROUTES:
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method, headers=self.headers)
                self.assertEqual(response.status_code, 401)

    def test_resource_not_found_precedes_malformed_update(self):
        for path in ('/tasks/99999', '/users/99999', '/categories/99999'):
            response = self.client.put(path, data='{', content_type='application/json',
                                       headers=self.headers)
            self.assertEqual(response.status_code, 404)
            self.assertTrue(response.is_json)

    def test_new_input_failures_use_approved_json(self):
        cases = (
            ('POST', '/tasks', {'title': 42}),
            ('POST', '/tasks', {'title': 'Válido', 'priority': True}),
            ('POST', '/tasks', {'title': 'Válido', 'tags': [42]}),
            ('POST', '/tasks', {'title': 'Válido', 'description': []}),
            ('PUT', '/tasks/1', {'title': None}),
            ('PUT', '/tasks/1', ['x']),
            ('PUT', '/users/1', {'active': 'true'}),
            ('PUT', '/users/1', {'name': None}),
            ('PUT', '/users/1', ['x']),
            ('POST', '/users', {'name': 42, 'email': 'test@example.test',
                                'password': self.seed_password}),
            ('POST', '/categories', {'name': 42}),
            ('PUT', '/categories/1', {'name': None}),
            ('PUT', '/categories/1', ['x']),
            ('POST', '/login', ['x']),
            ('POST', '/login', {'email': 'joao@email.com', 'password': 42}),
        )
        for method, path, body in cases:
            with self.subTest(method=method, path=path, body_type=type(body).__name__):
                response = self.client.open(path, method=method, json=body, headers=self.headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json, {'error': 'Dados inválidos'})
        response = self.client.get('/tasks/search?priority=invalid')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {'error': 'Dados inválidos'})

    def test_existing_business_errors_keep_messages(self):
        cases = (
            ('POST', '/tasks', {'title': ''}, 'Título é obrigatório'),
            ('POST', '/tasks', {'title': ['x']}, 'Título muito curto'),
            ('PUT', '/tasks/1', {'status': None}, 'Status inválido'),
            ('POST', '/tasks', {'title': 'Válido', 'priority': 0},
             'Prioridade deve ser entre 1 e 5'),
            ('PUT', '/tasks/1', {'due_date': 42}, 'Formato de data inválido'),
            ('POST', '/users', {'name': 'Nome', 'email': 'email', 'password': self.seed_password},
             'Email inválido'),
            ('PUT', '/users/1', {'password': []}, 'Senha muito curta'),
        )
        for method, path, body, message in cases:
            response = self.client.open(path, method=method, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json, {'error': message})

    def test_optional_null_unknown_fields_and_empty_category_update(self):
        response = self.client.post('/tasks', json={
            'title': '   ', 'description': None, 'due_date': None,
            'tags': None, 'user_id': None, 'category_id': None, 'unknown': True,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['title'], '   ')
        self.assertIsNone(response.json['description'])
        self.assertEqual(response.json['tags'], [])
        response = self.client.put('/categories/1', json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_malformed_and_framework_errors_keep_html(self):
        self.assertFalse(self.app.debug)
        response = self.client.post('/tasks', data='{', content_type='application/json',
                                    headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Failed to decode JSON object', response.get_data(as_text=True))
        self.assertEqual(response.mimetype, 'text/html')
        response = self.client.post('/tasks', data='{}', content_type='text/plain',
                                    headers=self.headers)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.mimetype, 'text/html')
        for method, path, expected in (('GET', '/unknown', 404), ('PATCH', '/health', 405)):
            response = self.client.open(path, method=method)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(response.mimetype, 'text/html')

    def test_cors_default_denies_and_explicit_allowlist_handles_preflight(self):
        origin = 'https://allowed.example.test'
        response = self.client.get('/health', headers={'Origin': origin})
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        allowed_app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                  'CORS_ORIGINS': [origin]})
        client = allowed_app.test_client()
        response = client.get('/health', headers={'Origin': origin})
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
        response = client.options('/tasks', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'X-Admin-Token',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
        self.assertIn('POST', response.headers['Access-Control-Allow-Methods'])
        self.assertIn('X-Admin-Token', response.headers['Access-Control-Allow-Headers'])
        response = client.get('/health', headers={'Origin': 'https://untrusted.example.test'})
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_password_is_omitted_from_every_user_response_and_login(self):
        created = self.client.post('/users', json={
            'name': 'Conta de teste', 'email': 'new@example.test',
            'password': self.seed_password,
        }, headers=self.headers)
        self.assertEqual(created.status_code, 201)
        user_id = created.json['id']
        responses = [created, self.client.get(f'/users/{user_id}', headers=self.headers),
                     self.client.put(f'/users/{user_id}', json={'name': 'Atualizado'},
                                     headers=self.headers)]
        for response in responses:
            self.assertNotIn('password', response.json)
        login = self.client.post('/login', json={
            'email': 'new@example.test', 'password': self.seed_password})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(set(login.json), {'message', 'user'})
        self.assertNotIn('password', login.json['user'])
        self.assertNotIn('token', login.json)

    def test_legacy_hash_migrates_only_after_valid_active_login(self):
        user = db.session.get(User, 1)
        legacy = hashlib.md5(self.seed_password.encode(), usedforsecurity=False).hexdigest()
        user.password = legacy
        db.session.commit()
        response = self.client.post('/login', json={
            'email': user.email, 'password': secrets.token_urlsafe(16)})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(user.password == legacy)
        user.active = False
        db.session.commit()
        response = self.client.post('/login', json={
            'email': user.email, 'password': self.seed_password})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(user.password == legacy)
        user.active = True
        db.session.commit()
        response = self.client.post('/login', json={
            'email': user.email, 'password': self.seed_password})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(user.password == legacy)
        self.assertTrue(check_password_hash(user.password, self.seed_password))
        self.assertNotIn('password', response.json['user'])

    def test_seed_requires_environment_before_schema_or_data_access(self):
        before = self.snapshot()
        with patch('seed.initialize_database') as initialize:
            with self.assertRaises(ValueError):
                seed_data(self.app, passwords={})
        initialize.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_seed_rolls_back_deletion_and_partial_inserts(self):
        before = self.snapshot()
        original_flush = persistence.flush
        calls = 0

        def fail_after_users():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('Falha simulada')
            original_flush()

        with patch('services.seed_service.persistence.flush', side_effect=fail_after_users):
            with self.assertRaises(PersistenceError):
                populate(self.passwords)
        self.assertEqual(calls, 2)
        db.session.expire_all()
        self.assertEqual(self.snapshot(), before)

    def test_internal_failures_preserve_responses_without_sensitive_logs(self):
        sensitive_detail = secrets.token_urlsafe(32)
        with patch('controllers.task_controller.task_service.stats',
                   side_effect=RuntimeError(sensitive_detail)):
            with patch.object(self.app.logger, 'error') as log:
                response = self.client.get('/tasks/stats')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, 'text/html')
        self.assertNotIn(sensitive_detail, response.get_data(as_text=True))
        self.assertNotIn(sensitive_detail, str(log.call_args))
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError(sensitive_detail)):
            with patch.object(self.app.logger, 'error') as log:
                response = self.client.post('/tasks', json={'title': 'Falha simulada'},
                                            headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {'error': 'Erro ao criar task'})
        self.assertNotIn(sensitive_detail, str(log.call_args))

    def test_seed_keeps_ids_relations_counts_and_configured_passwords(self):
        populate(self.passwords)
        self.assertEqual(list(db.session.scalars(select(User.id).order_by(User.id))), [1, 2, 3])
        self.assertEqual(list(db.session.scalars(select(Category.id).order_by(Category.id))), [1, 2, 3, 4])
        self.assertEqual(list(db.session.scalars(select(Task.id).order_by(Task.id))), list(range(1, 11)))
        for user in db.session.scalars(select(User)):
            self.assertTrue(check_password_hash(user.password, self.seed_password))
        summary = self.client.get('/reports/summary', headers=self.headers).json
        self.assertEqual(summary['overview'], {'total_tasks': 10, 'total_users': 3, 'total_categories': 4})
        self.assertEqual(summary['tasks_by_status'], {'pending': 6, 'in_progress': 2, 'done': 1, 'cancelled': 1})
        self.assertEqual(summary['overdue']['count'], 2)
        self.assertEqual(self.client.get('/tasks/stats').json['completion_rate'], 10.0)

    def test_empty_database_preserves_integer_zero_and_empty_lists(self):
        with persistence.transaction('Falha de teste'):
            db.session.execute(db.delete(Task))
            db.session.execute(db.delete(User))
            db.session.execute(db.delete(Category))
        stats = self.client.get('/tasks/stats').json
        self.assertEqual(stats['total'], 0)
        self.assertIs(type(stats['completion_rate']), int)
        self.assertEqual(self.client.get('/tasks').json, [])
        self.assertEqual(self.client.get('/categories').json, [])
        self.assertEqual(self.client.get('/users', headers=self.headers).json, [])
        summary = self.client.get('/reports/summary', headers=self.headers).json
        self.assertEqual(summary['user_productivity'], [])
        self.assertEqual(summary['overdue'], {'count': 0, 'tasks': []})

    def test_queries_stay_bounded_when_resources_grow(self):
        paths = ('/tasks', '/users', '/categories', '/reports/summary')

        def query_counts():
            counts = {}
            for path in paths:
                statements = []
                def track(*args):
                    statements.append(1)
                db.session.expire_all()
                event.listen(db.engine, 'before_cursor_execute', track)
                try:
                    response = self.client.get(path, headers=self.headers)
                    self.assertEqual(response.status_code, 200)
                finally:
                    event.remove(db.engine, 'before_cursor_execute', track)
                counts[path] = len(statements)
            return counts

        before = query_counts()
        encoded = db.session.get(User, 1).password
        for index in range(20):
            user = User(name=f'Pessoa {index}', email=f'person-{index}@example.test', password=encoded)
            category = Category(name=f'Categoria {index}')
            db.session.add_all([user, category])
            db.session.flush()
            db.session.add(Task(title=f'Tarefa {index}', user_id=user.id, category_id=category.id))
        db.session.commit()
        self.assertEqual(query_counts(), before)
        self.assertLessEqual(before['/tasks'], 1)
        self.assertLessEqual(before['/reports/summary'], 8)


if __name__ == '__main__':
    unittest.main()
