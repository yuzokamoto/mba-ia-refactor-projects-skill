"""Testes estáticos de MVC com projetos sintéticos e sem executar aplicações."""
import sys
sys.dont_write_bytecode = True

import ast
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'check_mvc.py'
CANARY = 'CANARY_MVC_NEVER_DISCLOSE_782691'


class CheckMvcTests(unittest.TestCase):
    def setUp(self):
        # Fora do diretório da skill: os testes não podem deixar arquivos na cópia distribuída.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def run_check(self, *args):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT),
                                 '--project-root', str(self.root), *args],
                                capture_output=True, text=True, timeout=10)
        self.assertFalse(CANARY in result.stdout + result.stderr,
                         'A saída contém texto-fonte sintético sensível.')
        return result

    def assert_rule(self, result, file, line, rule):
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn('MVC_VIOLATION {}:{} {}\n'.format(file, line, rule), result.stdout)

    def test_clean_flask_mvc(self):
        self.put('app.py', 'from flask import Flask\nfrom routes.tasks import bp\n'
                 'def create_app():\n    app = Flask(__name__)\n'
                 '    app.register_blueprint(bp)\n    return app\n')
        self.put('routes/tasks.py', 'from flask import Blueprint\n'
                 'from controllers.tasks import list_tasks\nbp = Blueprint("tasks", __name__)\n'
                 '@bp.get("/tasks")\ndef listing():\n    return list_tasks()\n')
        self.put('controllers/tasks.py', 'from flask import jsonify\n'
                 'from services.tasks import fetch_tasks\ndef list_tasks():\n'
                 '    tasks = fetch_tasks()\n    return jsonify(tasks), 200\n')
        self.put('services/tasks.py', 'from models.task import Task\ndef fetch_tasks():\n'
                 '    return [t.name for t in Task.query.all()]\n')
        self.put('models/task.py', 'class Task:\n    name = "task"\n')
        self.put('config/settings.py', 'DEBUG = False\n')
        self.put('middlewares/error_handler.py', 'from flask import jsonify\n'
                 'def error_handler(error):\n    return jsonify(error="failed"), 500\n')
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(result.stdout.endswith('MVC=ok FILES=7 VIOLATIONS=0 WARNINGS=0\n'))
        self.assertIn('LAYER routes/tasks.py routes\n', result.stdout)

    def test_clean_express_mvc(self):
        self.put('src/app.js', "const express = require('express');\nconst app = express();\n"
                 "app.use('/api', require('./routes/tasks'));\n")
        self.put('src/routes/tasks.js', "const router = require('express').Router();\n"
                 "const c = require('../controllers/tasks');\nrouter.get('/tasks', c.listTasks);\n")
        self.put('src/controllers/tasks.js', "const service = require('../services/tasks');\n"
                 'exports.listTasks = (req, res) => {\n'
                 '  const tasks = service.listTasks();\n  return res.status(200).json(tasks);\n};\n')
        self.put('src/services/tasks.js', "const model = require('../models/task');\n"
                 'exports.listTasks = () => model.all();\n')
        self.put('src/models/task.js', "exports.all = () => db.all('SELECT * FROM tasks');\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(result.stdout.endswith('MVC=ok FILES=5 VIOLATIONS=0 WARNINGS=0\n'))

    def test_layers_and_json(self):
        expected = {'TaskController.py': 'controllers', 'APIUserController.py': 'controllers',
                    'TASKCONTROLLER.PY': 'controllers', 'user_routes.py': 'routes',
                    'src/task.routes.ts': 'routes', 'src/View/item.py': 'routes',
                    'src/Router/task.js': 'routes', 'src/controllers/__init__.py': 'controllers',
                    'src/userMiddleware.js': 'middlewares', 'UserValidator.py': 'validators',
                    'schemas/task.py': 'validators', 'serializers/task.py': 'validators',
                    'validation/task.py': 'validators', 'taskRepository.py': 'models',
                    'dao/task.py': 'models', 'userService.py': 'services',
                    'Settings.py': 'config', 'errors.py': 'errors', 'exceptions.py': 'errors',
                    'app.py': 'entry', 'src/index.js': 'entry', 'nested/app.py': 'other',
                    'helpers.py': 'other', 'services/handlers/tasks.py': 'services'}
        for path in expected:
            self.put(path, '')
        result = self.run_check('--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['mvc'], 'ok')
        self.assertEqual({item['path']: item['layer'] for item in data['files']}, expected)
        self.assertEqual(data['violations'], [])
        self.assertEqual(data['warnings'], [])
        self.assertEqual(self.run_check().stdout, self.run_check().stdout)

    def test_python_routes_import_data_and_resolve_aliases(self):
        self.put('controllers/tasks.py', '')
        self.put('data/store.py', 'class Store: pass\n')
        self.put('models/custom.py', 'class Item: pass\n')
        self.put('services/task.py', 'def create(): pass\n')
        cases = [('from models.custom import Item', 1),
                 ('import services.task as tasks', 1),
                 ('from database import db', 1), ('import db', 1),
                 ('from ..models.custom import Item', 1),
                 ('from data import store', None),
                 ('from controllers.tasks import listing', None),
                 ('from flask import request', None)]
        for statement, expected in cases:
            with self.subTest(statement=statement):
                self.put('routes/tasks.py', statement + '\n')
                result = self.run_check()
                if expected:
                    self.assert_rule(result, 'routes/tasks.py', expected, 'routes_import_data')
                else:
                    self.assertNotIn('routes_import_data', result.stdout)
        self.put('data/store.py', '')
        self.put('routes/tasks.py', 'from models import custom\n')
        self.assert_rule(self.run_check(), 'routes/tasks.py', 1, 'routes_import_data')

    def test_python_route_size_ignores_comments_docstrings_and_signature(self):
        self.put('controllers/tasks.py', '')
        body = ''.join('    value_{} = {}\n'.format(i, i) for i in range(8))
        source = ('from flask import Blueprint\nbp = Blueprint("tasks", __name__)\n'
                  '@bp.get("/tasks")\ndef listing(\n    argument=None,\n):\n'
                  '    """Documentação\n    extensa.\n    """\n    # Comentário\n\n')
        self.put('routes/tasks.py', source + body)
        self.assertEqual(self.run_check().returncode, 0)
        self.put('routes/tasks.py', source + body + '    return value_0\n')
        self.assert_rule(self.run_check(), 'routes/tasks.py', 4, 'route_handler_too_long')
        self.put('routes/tasks.py', '')
        self.put('services/handlers/tasks.py', source + body + '    return value_0\n')
        result = self.run_check()
        self.assert_rule(result, 'services/handlers/tasks.py', 4, 'route_handler_too_long')
        self.assert_rule(result, 'services/handlers/tasks.py', 3, 'route_outside_http_layer')

    def test_python_routes_outside_layer_and_moved_handlers(self):
        self.put('controllers/tasks.py', '')
        self.put('services/handlers/task.py', 'from flask import request, jsonify\n'
                 '@bp.route("/tasks", methods=["POST"])\ndef create():\n'
                 '    return jsonify(request.json)\n')
        result = self.run_check()
        self.assert_rule(result, 'services/handlers/task.py', 2, 'route_outside_http_layer')
        self.assert_rule(result, 'services/handlers/task.py', 4, 'http_in_domain')
        for path in ['validators/bad.py', 'models/bad.py', 'helpers/bad.py']:
            self.put(path, 'app.add_url_rule("/tasks", view_func=handler)\n')
            self.assert_rule(self.run_check(), path, 1, 'route_outside_http_layer')
        self.put('services/handlers/task.py', 'def create(data):\n    return data\n')
        self.assertNotIn('services/handlers/task.py:2 route_outside_http_layer', self.run_check().stdout)

    def test_python_direct_db_access_in_each_http_layer(self):
        self.put('controllers/__init__.py', '')
        expressions = ['db.session.add(item)', 'Task.query.all()', 'select(Task)',
                       'connection.execute("' + CANARY + '")', 'cursor.fetchone()',
                       'connection.commit()', 'sqlite3.connect("file.db")', 'get_db()',
                       'current.rollback()', 'connection.executemany("' + CANARY + '", rows)',
                       'connection.executescript("' + CANARY + '")']
        for layer in ['routes', 'controllers', 'validators', 'middlewares', 'entry']:
            path = 'app.py' if layer == 'entry' else layer + '/bad.py'
            for expression in expressions:
                with self.subTest(layer=layer, expression=expressions.index(expression)):
                    self.put(path, 'def run():\n    ' + expression + '\n')
                    self.assert_rule(self.run_check(), path, 2, 'db_access_in_http_layer')
            self.put(path, 'def run():\n    return {"query": "db.session.commit()"}\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.put('models/persist.py', '\n'.join(expressions) + '\n')
        self.assertEqual(self.run_check().returncode, 0)

    def test_python_domain_http_aliases_and_status_occurrences(self):
        self.put('services/task.py', 'from flask import request as incoming, jsonify as output\n'
                 'import flask as web\n'
                 'def create():\n    value = incoming.json\n    return output(value), 400\n'
                 'def update():\n    return web.make_response({}, status=422)\n')
        result = self.run_check()
        self.assert_rule(result, 'services/task.py', 4, 'http_in_domain')
        self.assert_rule(result, 'services/task.py', 5, 'status_in_domain')
        self.assert_rule(result, 'services/task.py', 7, 'http_in_domain')
        self.assert_rule(result, 'services/task.py', 7, 'status_in_domain')
        self.put('services/task.py', 'def create():\n    return {"status": 400}, 600\n'
                 'def response():\n    return factory(status=99)\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.put('models/task.py', 'from werkzeug.wrappers import Response\n'
                 'def create():\n    return Response(status=400, status_code=401, code=402)\n')
        data = json.loads(self.run_check('--json').stdout)
        self.assertEqual(sum(v['rule'] == 'status_in_domain' for v in data['violations']), 3)
        self.assertTrue(any(v['rule'] == 'http_in_domain' and v['line'] == 3 for v in data['violations']))

    def test_python_string_dispatch_variants_and_normal_controller(self):
        cases = [('def run(action):\n    return getattr(service, action)()\n', 2),
                 ('def run():\n    return dispatch("create_task")\n', 2),
                 ('def run():\n    return service.handle("create_task")\n', 2),
                 ('def run():\n    return execute("create_task")\n', 2),
                 ('handlers = {"a": create, "b": update, "c": remove}\n'
                  'def run(action):\n    return handlers[action]()\n', 3)]
        for source, line in cases:
            with self.subTest(source=cases.index((source, line))):
                self.put('controllers/tasks.py', source)
                self.assert_rule(self.run_check(), 'controllers/tasks.py', line, 'string_dispatch_controller')
        for source in ['def run():\n    return getattr(service, "create")()\n',
                       'handlers = {"a": 1, "b": 2, "c": 3}\n'
                       'def run(action):\n    return handlers[action]\n',
                       'def run():\n    return service.create_task("title")\n']:
            self.put('controllers/tasks.py', source)
            self.assertNotIn('string_dispatch_controller', self.run_check().stdout)

    def test_sql_and_keyword_literals_are_not_string_dispatch(self):
        # SQL em execute() é acesso a dados, não despacho por nome de ação.
        triple = '"' * 3
        for source in ['def run(cursor):\n    cursor.execute("SELECT * FROM t WHERE id = ?", (1,))\n',
                       'def run(cursor):\n    cursor.execute("VACUUM")\n',
                       'def run(db):\n    db.execute(' + triple + '\n        UPDATE t SET a = 1\n    '
                       + triple + ')\n']:
            with self.subTest(source=source):
                self.put('controllers/tasks.py', source)
                result = self.run_check()
                self.assertNotIn('string_dispatch_controller', result.stdout)
                self.assertIn('db_access_in_http_layer', result.stdout)
        self.put('controllers/tasks.py', '')
        self.put('controllers/orders.js', 'function run(db) {\n  db.execute("SELECT * FROM t");\n'
                 '  return execute("create_order");\n}\nmodule.exports = { run };\n')
        result = self.run_check()
        self.assertIn('MVC_VIOLATION controllers/orders.js:3 string_dispatch_controller\n', result.stdout)
        self.assertNotIn('controllers/orders.js:2 string_dispatch_controller', result.stdout)

    def test_python_syntax_error_is_safe_and_project_is_not_executed(self):
        self.put('app.py', 'raise RuntimeError("' + CANARY + '")\n')
        self.put('broken.py', 'value = "' + CANARY + '"\ndef broken(:\n')
        result = self.run_check()
        self.assert_rule(result, 'broken.py', 2, 'syntax_error')
        self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_db_helper_return_taint_cross_module_and_transitive(self):
        self.put('helpers.py', 'def model_query(model):\n    return model.query\n'
                 'def connection():\n    value = sqlite3.connect("file.db")\n    return value\n'
                 'def alias(model):\n    return model_query(model)\n')
        self.put('routes/task.py', 'from helpers import model_query as query_for\n'
                 'from helpers import connection, alias\n'
                 'def listing():\n    value = query_for(Task)\n'
                 '    other = alias(Task)\n    return connection()\n')
        self.put('controllers/task.py', '')
        result = self.run_check()
        for line in [4, 5, 6]:
            self.assert_rule(result, 'routes/task.py', line, 'db_access_via_helper')
        self.put('helpers.py', 'def model_query(model):\n    return {"query": model}\n'
                 'def connection():\n    return [1, 2]\n'
                 'def alias(model):\n    return model_query(model)\n')
        self.assertNotIn('db_access_via_helper', self.run_check().stdout)
        self.put('unrelated.py', 'def model_query(model):\n    return model.query\n')
        self.assertNotIn('db_access_via_helper', self.run_check().stdout)

    def test_no_controller_and_entry_handler_warning(self):
        self.put('app.py', '@app.get("/health")\ndef health():\n    return "ok"\n')
        self.assert_rule(self.run_check(), 'app.py', 1, 'no_controller_layer')
        self.put('controllers/task.py', '')
        self.assertEqual(self.run_check().returncode, 0)
        self.put('app.py', '@app.get("/tasks")\ndef listing():\n' +
                 ''.join('    value_{} = {}\n'.format(i, i) for i in range(9)))
        result = self.run_check()
        self.assert_rule(result, 'app.py', 2, 'route_handler_too_long')
        self.assertIn('MVC_WARNING app.py:2 entry_has_handlers\n', result.stdout)
        self.put('app.py', '')
        self.assertNotIn('no_controller_layer', self.run_check().stdout)

    def test_passthrough_is_only_warning_and_all_functions_must_delegate(self):
        self.put('controllers/task.py', 'def create(data):\n    """Encaminha."""\n'
                 '    return service.create(data)\n'
                 'async def update(data):\n    return service.update(data)\n')
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('MVC_WARNING controllers/task.py:1 pass_through_controller\n', result.stdout)
        self.put('controllers/task.py', 'def create(data):\n    value = service.create(data)\n    return value\n')
        self.assertNotIn('pass_through_controller', self.run_check().stdout)

    def test_god_module_resource_and_size_threshold(self):
        self.put('controllers/task.py', '')
        self.put('routes/task.py', '@bp.get("/api/v1/tasks/<id>")\ndef tasks():\n    return c.tasks()\n'
                 '@bp.get("/api/v1/users/:id")\ndef users():\n    return c.users()\n'
                 '@bp.get("/usuarios")\ndef usuarios():\n    return c.usuarios()\n')
        names = ('def list_task():\n    pass\ndef list_user():\n    pass\n'
                 'class Usuario:\n    pass\n')
        self.put('services/all.py', names + ''.join('value_{} = {}\n'.format(i, i) for i in range(295)))
        self.assert_rule(self.run_check(), 'services/all.py', 1, 'god_module')
        self.put('services/all.py', names + ''.join('value_{} = {}\n'.format(i, i) for i in range(294)))
        self.assertNotIn('god_module', self.run_check().stdout)
        self.put('services/all.py', 'def list_task():\n    pass\n' +
                 ''.join('value_{} = {}\n'.format(i, i) for i in range(310)))
        self.assertNotIn('god_module', self.run_check().stdout)

    def test_excluded_files_links_and_foreign_languages_are_not_parsed(self):
        excluded = ['.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__',
                    '.agents', '.claude', 'tests', 'test', '__tests__', 'reports',
                    'instance', 'dist', 'build', 'coverage', '.handoff', '.worktrees']
        for directory in excluded:
            self.put(directory + '/broken.py', 'def broken(:\n')
        self.put('ignored.java', 'broken syntax')
        self.put('app.py', '# Apenas comentário\n')
        (self.root / 'linked.py').symlink_to(self.root / '.venv/broken.py')
        (self.root / 'linked').symlink_to(self.root / '.venv', target_is_directory=True)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(result.stdout.endswith('MVC=ok FILES=1 VIOLATIONS=0 WARNINGS=0\n'))

    def test_js_rules_imports_db_http_status_dispatch_and_route_location(self):
        self.put('controllers/task.js', '')
        self.put('routes/task.js', "const service = require('../services/task');\n"
                 "import { Task } from '../models/task.js';\n"
                 "router.get('/tasks', (req, res) => db.all('" + CANARY + "'));\n")
        self.put('services/task.js', 'exports.create = (req, res) => {\n'
                 "  req.body;\n  return res.status(400).json({statusCode: 401, status: 422});\n};\n"
                 "app.post('/tasks', handler);\n")
        self.put('models/task.js', '')
        result = self.run_check()
        for line in [1, 2]:
            self.assert_rule(result, 'routes/task.js', line, 'routes_import_data')
        self.assert_rule(result, 'routes/task.js', 3, 'db_access_in_http_layer')
        self.assert_rule(result, 'services/task.js', 2, 'http_in_domain')
        self.assert_rule(result, 'services/task.js', 3, 'http_in_domain')
        self.assert_rule(result, 'services/task.js', 3, 'status_in_domain')
        self.assert_rule(result, 'services/task.js', 5, 'route_outside_http_layer')
        data = json.loads(self.run_check('--json').stdout)
        self.assertEqual(sum(v['rule'] == 'status_in_domain' for v in data['violations']), 3)
        self.put('controllers/task.js', "exports.create = () => dispatch('create_task');\n")
        self.assert_rule(self.run_check(), 'controllers/task.js', 1, 'string_dispatch_controller')

    def test_js_each_persistence_form_and_non_code_literals(self):
        expressions = ['db.run()', 'db.all()', 'db.get()', 'db.each()', 'db.exec()',
                       'db.prepare()', 'db.serialize()', 'knex("tasks")',
                       'sequelize.models.Task.findAll()', 'client.query("sql")',
                       'new sqlite3.Database("file.db")']
        for expression in expressions:
            with self.subTest(expression=expression):
                self.put('src/app.js', expression + ';\n')
                self.assert_rule(self.run_check(), 'src/app.js', 1, 'db_access_in_http_layer')
        self.put('src/app.js', '// db.run();\n/* sequelize.query(); */\n'
                 'const text = "db.run(); req.json; dispatch(\\"x\\")";\n')
        self.put('services/task.js', 'const text = "res.status(400); req.body";\n'
                 '// req.body\n/* res.status(401) */\n'
                 'exports.create = data => ({status: 99, statusCode: 600});\n')
        self.assertEqual(self.run_check().returncode, 0)

    def test_js_inline_callback_size_comments_multiline_signature_and_god_class(self):
        self.put('controllers/task.js', '')
        source = "const app = express();\napp.get('/tasks', async (\n  req,\n  res\n) => {\n"
        body = ''.join('  const value{} = {};\n'.format(i, i) for i in range(8))
        self.put('src/app.js', source + '// Comentário\n/*\n Bloco\n*/\n' + body + '});\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.put('src/app.js', source + body + '  return res.json(value0);\n});\n')
        result = self.run_check()
        self.assert_rule(result, 'src/app.js', 2, 'route_handler_too_long')
        self.assertIn('MVC_WARNING src/app.js:2 entry_has_handlers\n', result.stdout)
        self.put('src/app.js', 'class Server {\n  setup() {\n' + source + body +
                 "  db.run('sql');\n});\n  }\n}\n")
        result = self.run_check()
        self.assert_rule(result, 'src/app.js', 4, 'route_handler_too_long')
        self.assert_rule(result, 'src/app.js', 16, 'db_access_in_http_layer')

    def test_legacy_flat_flask_calls_sql_controller(self):
        self.put('app.py', 'from flask import Flask\nimport controllers\napp = Flask(__name__)\n'
                 '@app.get("/tasks")\ndef listing():\n    return controllers.list_tasks()\n')
        self.put('controllers.py', 'def list_tasks():\n'
                 '    connection = sqlite3.connect("' + CANARY + '")\n'
                 '    return connection.execute("select 1").fetchall()\n')
        self.assert_rule(self.run_check(), 'controllers.py', 2, 'db_access_in_http_layer')
        self.assert_rule(self.run_check(), 'controllers.py', 3, 'db_access_in_http_layer')

    def test_ordinary_dictionary_get_in_domain_is_not_route(self):
        self.put('services/task.py', 'def create(data):\n    return data.get("title")\n')
        self.assertEqual(self.run_check().returncode, 0)

    def test_python_39_syntax_and_no_bytecode(self):
        for path in [SCRIPT, Path(__file__)]:
            ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 9))
        self.put('app.py', 'raise RuntimeError("' + CANARY + '")\n')
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(list(self.root.rglob('__pycache__')), [])

    def test_js_dictionary_dispatch_and_passthrough_warning(self):
        self.put('controllers/task.js', 'const actions = {"create": create, "update": update, "delete": remove};\n'
                 'exports.run = action => actions[action]();\n')
        self.assert_rule(self.run_check(), 'controllers/task.js', 2, 'string_dispatch_controller')
        self.put('controllers/task.js', 'const actions = {"a": 1, "b": 2, "c": 3};\n'
                 'exports.run = action => actions[action];\n')
        self.assertNotIn('string_dispatch_controller', self.run_check().stdout)
        self.put('controllers/task.js', 'exports.createTask = data => service.createTask(data);\n'
                 'function updateTask(data) { return service.updateTask(data); }\n')
        result = self.run_check()
        self.assertEqual(result.returncode, 0)
        self.assertIn('MVC_WARNING controllers/task.js:1 pass_through_controller\n', result.stdout)
        self.put('controllers/task.js', 'exports.createTask = data => {\n'
                 '  const value = service.createTask(data);\n  return value;\n};\n')
        self.assertNotIn('pass_through_controller', self.run_check().stdout)

    def test_js_god_module_function_names_not_arbitrary_identifiers(self):
        self.put('controllers/task.js', '')
        self.put('routes/task.js', "router.get('/api/v2/tasks', c.list);\n"
                 "router.get('/api/v2/users', c.list);\nrouter.get('/orders', c.list);\n")
        names = 'function taskList() {}\nfunction userList() {}\nclass OrderStore {}\n'
        self.put('services/all.js', names + ''.join('const value{} = {};\n'.format(i, i) for i in range(298)))
        self.assert_rule(self.run_check(), 'services/all.js', 1, 'god_module')
        self.put('services/all.js', names + ''.join('const value{} = {};\n'.format(i, i) for i in range(297)))
        self.assertNotIn('god_module', self.run_check().stdout)
        self.put('services/all.js', 'function taskList() {}\nconst userOrder = 1;\n' +
                 ''.join('const value{} = {};\n'.format(i, i) for i in range(310)))
        self.assertNotIn('god_module', self.run_check().stdout)

    def test_js_returned_db_objects_across_commonjs_and_esm(self):
        self.put('helpers.js', 'exports.modelQuery = model => model.query;\n'
                 'exports.connection = () => { return new sqlite3.Database("file.db"); };\n')
        self.put('routes/task.js', "const helpers = require('../helpers');\n"
                 "import { connection as open } from '../helpers.js';\n"
                 'router.get("/tasks", (req, res) => helpers.modelQuery(Task));\n'
                 'const value = open();\n')
        self.put('controllers/task.js', '')
        result = self.run_check()
        self.assert_rule(result, 'routes/task.js', 3, 'db_access_via_helper')
        self.assert_rule(result, 'routes/task.js', 4, 'db_access_via_helper')
        self.put('helpers.js', 'exports.modelQuery = model => [model];\n'
                 'exports.connection = () => [1, 2];\n')
        self.assertNotIn('db_access_via_helper', self.run_check().stdout)
        self.put('unrelated.js', 'exports.modelQuery = model => model.query;\n')
        self.assertNotIn('db_access_via_helper', self.run_check().stdout)

    def test_python_helper_returns_session_cursor_and_aliased_sqlite(self):
        self.put('helpers.py', 'import sqlite3 as sql\n'
                 'def session():\n    return db.session\n'
                 'def cursor_for(conn):\n    return conn.cursor()\n'
                 'def connection():\n    return sql.connect("file.db")\n')
        self.put('controllers/task.py', 'import helpers\n'
                 'def run():\n    helpers.session()\n    helpers.cursor_for(None)\n    helpers.connection()\n')
        result = self.run_check()
        for line in [3, 4, 5]:
            self.assert_rule(result, 'controllers/task.py', line, 'db_access_via_helper')

    def test_python_dispatch_dictionary_get_and_literal_values(self):
        self.put('controllers/task.py', 'actions = {"create": service.create, "update": service.update, "delete": service.delete}\n'
                 'def run(action):\n    handler = actions.get(action)\n    return handler()\n')
        self.assert_rule(self.run_check(), 'controllers/task.py', 3, 'string_dispatch_controller')
        self.put('controllers/task.py', 'actions = {"create": 1, "update": 2, "delete": 3}\n'
                 'def run(action):\n    return actions.get(action)\n')
        self.assertNotIn('string_dispatch_controller', self.run_check().stdout)

    def test_head_decorator_counts_as_endpoint(self):
        self.put('app.py', '@app.head("/health")\ndef health():\n    return ""\n')
        self.assert_rule(self.run_check(), 'app.py', 1, 'no_controller_layer')
        self.put('controllers/task.py', '')
        self.assertEqual(self.run_check().returncode, 0)

    def test_nested_function_decorators_and_signatures_not_counted_as_body(self):
        self.put('controllers/task.py', '')
        self.put('routes/task.py', 'def handler():\n'
                 '    @decorate\n    def nested(\n        value=None,\n    ):\n'
                 '        return value\n'
                 + ''.join('    value_{} = {}\n'.format(i, i) for i in range(7)))
        self.assertEqual(self.run_check().returncode, 0)

    def test_js_status_literal_boundaries_and_string_keys(self):
        self.put('services/task.js', 'const data = {"status": 400, status: 4000, statusCode: 99};\n'
                 'const other = {status: 401.5, statusCode: 600};\n')
        data = json.loads(self.run_check('--json').stdout)
        hits = [v for v in data['violations'] if v['rule'] == 'status_in_domain']
        self.assertEqual(hits, [{'file': 'services/task.js', 'line': 1, 'rule': 'status_in_domain'}])

    def test_js_comparison_tokens_do_not_loop(self):
        self.put('services/task.js', 'function create(item) {\n'
                 '  if (item === null) { return []; }\n  return item;\n}\n')
        self.assertEqual(self.run_check().returncode, 0)

    def test_ts_typed_route_callbacks_and_ts_import_resolution(self):
        self.put('controllers/task.ts', '')
        self.put('services/taskService.ts', 'export function listTask(): string[] { return []; }\n')
        self.put('routes/task.ts', "import svc from '../services/taskService';\n"
                 "router.get('/tasks', (req: Request, res: Response): void => {\n" +
                 ''.join('  const value{} = {};\n'.format(i, i) for i in range(9)) + '});\n')
        result = self.run_check()
        self.assert_rule(result, 'routes/task.ts', 1, 'routes_import_data')
        self.assert_rule(result, 'routes/task.ts', 2, 'route_handler_too_long')

    def test_js_string_values_are_not_callable_dispatch_tables(self):
        self.put('controllers/task.js', 'const actions = {"a": "create", "b": "update", "c": "delete"};\n'
                 'exports.run = action => actions[action];\n')
        self.assertNotIn('string_dispatch_controller', self.run_check().stdout)

    def test_commonjs_destructured_query_helper_and_default_export(self):
        self.put('helpers.js', 'function modelQuery(model) { return model.query; }\n'
                 'exports.modelQuery = modelQuery;\n')
        self.put('default.js', 'function modelQuery(model) { return model.query; }\n'
                 'module.exports = modelQuery;\n')
        self.put('controllers/task.js', "const { modelQuery: queryFor } = require('../helpers');\n"
                 "const queryDefault = require('../default');\n"
                 'exports.list = () => queryFor(Task);\n'
                 'exports.other = () => queryDefault(Task);\n')
        result = self.run_check()
        self.assert_rule(result, 'controllers/task.js', 3, 'db_access_via_helper')
        self.assert_rule(result, 'controllers/task.js', 4, 'db_access_via_helper')

    def test_python_relative_helper_import_and_reexport(self):
        self.put('helpers/query.py', 'def model_query(model):\n    return model.query\n')
        self.put('helpers/__init__.py', 'from .query import model_query\n')
        self.put('controllers/task.py', 'from helpers import model_query\n'
                 'def listing():\n    return model_query(Task)\n')
        self.assert_rule(self.run_check(), 'controllers/task.py', 3, 'db_access_via_helper')

    def test_bad_root_is_input_error(self):
        result = self.run_check('--project-root', str(self.root / 'missing'))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
