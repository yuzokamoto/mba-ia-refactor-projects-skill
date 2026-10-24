"""Testes sintéticos do inventário, sem executar código dos projetos."""
import sys
sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'inventory.py'
CANARY = 'CANARY_NEVER_DISCLOSE_739152'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT),
                                 '--project-root', str(self.root), *args],
                                capture_output=True, text=True)
        self.assertFalse(CANARY in result.stdout + result.stderr, 'A saída contém um segredo sintético.')
        return result

    def inventory(self):
        result = self.run_cli('--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_flask_monolith_and_source_exclusions(self):
        source = ('from flask import Flask\napp = Flask(__name__)\n'
                  'password = "' + CANARY + '"\n'
                  '@app.route("/users", methods=["GET", "POST"])\n'
                  'def users():\n    return "ok"\n'
                  '@app.route("/health")\ndef health():\n    return "ok"\n')
        self.put('app.py', source)
        self.put('requirements.txt', 'Flask==3.1.1\n')
        for directory in ['.venv', 'venv', 'node_modules', '.git', '__pycache__',
                          '.agents', '.claude', 'dist', 'build', 'instance']:
            self.put(directory + '/ignored.py', 'raise RuntimeError()\n')
        data = self.inventory()
        self.assertEqual(data['files'], [{'path': 'app.py', 'lines': 9}])
        self.assertEqual(data['loc'], 9)
        self.assertEqual(data['language'], 'Python')
        self.assertEqual(data['framework'], 'Flask')
        self.assertEqual([(e['method'], e['path']) for e in data['endpoints']],
                         [('GET', '/users'), ('POST', '/users'), ('GET', '/health')])
        text = self.run_cli().stdout
        for line in ['LANGUAGE=Python', 'FRAMEWORK=Flask', 'FILES=1', 'LOC=9',
                     'ENDPOINTS=3', 'DATA_STORES=0', 'DEPRECATIONS=0',
                     'FILE app.py 9', 'ENDPOINT GET /health app.py:7', 'ENTRY app.py:2']:
            self.assertIn(line, text)
        self.assertFalse(list(self.root.rglob('*.pyc')))

    def test_blueprints_imports_prefix_override_and_multiple_mounts(self):
        self.put('app.py', 'from flask import Flask\nfrom routes.users import bp as users\n'
                 'app = Flask(__name__)\napp.register_blueprint(users, url_prefix="/v1")\n'
                 'app.register_blueprint(users, url_prefix="/v2", name="second")\n')
        self.put('routes/users.py', 'from flask import Blueprint\n'
                 'bp = Blueprint("users", __name__, url_prefix="/ignored")\n'
                 '@bp.route("/users", methods=["GET", "POST"])\n'
                 'def users():\n    return []\n')
        self.put('routes/tasks.py', 'from flask import Blueprint\n'
                 'bp = Blueprint("tasks", __name__, url_prefix="/tasks")\n'
                 '@bp.route("/<int:id>")\ndef task(id):\n    return {}\n')
        self.put('local.py', 'from flask import Flask, Blueprint\napp=Flask(__name__)\n'
                 'local=Blueprint("local", __name__, url_prefix="/local")\n'
                 'app.register_blueprint(local)\n@local.post("/add")\ndef add(): pass\n')
        endpoints = self.inventory()['endpoints']
        self.assertEqual(sorted((e['method'], e['path']) for e in endpoints),
                         [('GET', '/tasks/<int:id>'), ('GET', '/v1/users'),
                          ('GET', '/v2/users'), ('POST', '/local/add'),
                          ('POST', '/v1/users'), ('POST', '/v2/users')])

    def test_express_router_prefix_require_import_and_comments(self):
        self.put('src/app.js', 'const express = require("express");\n'
                 'const router = require("./routes");\nconst app = express();\n'
                 'app.use("/api", router);\napp.get("/health", (req,res)=>res.send("ok"));\n'
                 '// app.get("/fake", nope);\nconst msg = "app.post(ignored)";\n')
        self.put('src/routes.js', 'const express = require("express");\n'
                 'const router = express.Router();\nrouter.get("/items", fn);\n'
                 'router.post("/items", fn);\nrouter.all("/any", fn);\nmodule.exports = router;\n')
        self.put('src/modern.mjs', 'import imported from "./routes.js";\n'
                 'const app = express();\napp.use("/v2", imported);\napp.delete("/gone", fn);\n')
        self.put('package.json', '{"dependencies":{"express":"^4.18.0"}}')
        data = self.inventory()
        self.assertEqual(data['framework'], 'Express')
        self.assertEqual(len(data['files']), 3)
        self.assertEqual(sorted((e['method'], e['path']) for e in data['endpoints']),
                         [('ALL', '/api/any'), ('ALL', '/v2/any'), ('DELETE', '/gone'),
                          ('GET', '/api/items'), ('GET', '/health'), ('GET', '/v2/items'),
                          ('POST', '/api/items'), ('POST', '/v2/items')])
        self.assertEqual(self.run_cli('--json').stdout, self.run_cli('--json').stdout)

    def test_metadata_versions_manifests_commands_and_data_stores(self):
        self.put('app.py', 'from flask import Flask\nimport sqlite3\napp=Flask(__name__)\n'
                 'db=sqlite3.connect("data.db")\n'
                 'DDL="CREATE TABLE IF NOT EXISTS orders (id INTEGER)"\n'
                 'class Customer(db.Model):\n    pass\n'
                 'class Product(db.Model):\n    __tablename__="products"\n')
        self.put('data.db', 'not-a-real-db')
        self.put('instance/cache.sqlite3', 'not-a-real-db')
        self.put('requirements.txt', 'Flask==3.1.1\nSQLAlchemy>=2.0\n')
        self.put('.venv/pyvenv.cfg', 'home = /usr/bin\nversion = 3.12.8\n')
        self.put('.venv/lib/python3.12/site-packages/flask-3.1.1.dist-info/METADATA',
                 'Name: Flask\nVersion: 3.1.1\n')
        self.put('.venv/lib/python3.12/site-packages/sqlalchemy-2.1.5.dist-info/METADATA',
                 'Name: SQLAlchemy\nVersion: 2.1.5\n')
        self.put('README.md', '# Fixture\n```sh\npython app.py\npython seed.py\n```\n'
                 'password="' + CANARY + '"\n')
        data = self.inventory()
        self.assertEqual(data['runtime']['python'], '3.12.8')
        self.assertEqual(data['runtime']['node'], 'unknown')
        packages = {p['name'].lower(): p for p in data['dependencies']}
        self.assertEqual(packages['flask']['declared'], '==3.1.1')
        self.assertEqual(packages['flask']['installed'], '3.1.1')
        self.assertEqual(packages['sqlalchemy']['installed'], '2.1.5')
        self.assertIn('requirements.txt', data['manifests'])
        self.assertEqual({d['path'] for d in data['data_stores']}, {'data.db', 'instance/cache.sqlite3'})
        self.assertEqual({t['name'] for t in data['tables']}, {'orders', 'customer', 'products'})
        self.assertEqual({c['kind'] for c in data['commands']}, {'start', 'seed'})
        self.assertIn('TABLE orders app.py:5', self.run_cli().stdout)

    def test_python_deprecations_respect_installed_versions_and_unknown_status(self):
        self.put('app.py', 'from datetime import datetime\nfrom flask.json import JSONEncoder\n'
                 'datetime.utcnow()\ndatetime.utcfromtimestamp(0)\nUser.query.get(1)\n'
                 'User.query.get_or_404(1)\ndb.session.query(User)\n'
                 '@app.before_first_request\ndef init(): pass\n'
                 'hashlib.md5(password.encode())\n# datetime.utcnow()\n')
        config = self.put('.venv/pyvenv.cfg', 'version = 3.12.3\n')
        flask = self.put('.venv/lib/python3.12/site-packages/flask.dist-info/METADATA',
                         'Name: Flask\nVersion: 3.0.0\n')
        sqlalchemy = self.put('.venv/lib/python3.12/site-packages/sa.dist-info/METADATA',
                              'Name: SQLAlchemy\nVersion: 2.1.5\n')
        expected = {'PY_DATETIME_UTCNOW', 'PY_DATETIME_UTCFROMTIMESTAMP', 'SA_QUERY_GET',
                    'SA_QUERY_GET_OR_404', 'SA_SESSION_QUERY', 'FLASK_BEFORE_FIRST_REQUEST',
                    'FLASK_JSON_ENCODER'}
        hits = self.inventory()['deprecations']
        self.assertEqual({h['rule'] for h in hits}, expected)
        self.assertEqual({h['status'] for h in hits}, {'deprecated'})
        self.assertEqual(next(h['severity'] for h in hits if h['rule'] == 'SA_SESSION_QUERY'), 'INFO')
        config.write_text('version = 3.11.9\n', encoding='utf-8')
        flask.write_text('Name: Flask\nVersion: 2.1.0\n', encoding='utf-8')
        sqlalchemy.write_text('Name: SQLAlchemy\nVersion: 1.4.0\n', encoding='utf-8')
        self.assertEqual(self.inventory()['deprecations'], [])
        for path in [config, flask, sqlalchemy]:
            path.unlink()
        hits = self.inventory()['deprecations']
        self.assertEqual({h['rule'] for h in hits}, expected)
        self.assertEqual({h['status'] for h in hits}, {'version-unknown'})
        self.assertIn('DEPRECATED PY_DATETIME_UTCNOW app.py:3', self.run_cli().stdout)

    def test_express_and_node_deprecations(self):
        self.put('app.js', 'res.send(200, {ok:true});\nreq.param("id");\n'
                 'res.sendfile("x");\nbodyParser();\nnew Buffer(20);\n'
                 'crypto.createCipher("aes", password);\nurl.parse(input);\nfs.exists(path, cb);\n'
                 '// new Buffer(10)\nconst text="req.param(ignored)";\n')
        self.put('package.json', '{"dependencies":{"express":"^4.0.0"},'
                 '"engines":{"node":">=20.0.0"},"scripts":{"start":"node app.js","seed":"node seed.js"}}')
        self.put('node_modules/express/package.json', '{"version":"4.22.1"}')
        data = self.inventory()
        self.assertEqual({h['rule'] for h in data['deprecations']},
                         {'EXPRESS_RES_SEND_STATUS_BODY', 'EXPRESS_REQ_PARAM',
                          'EXPRESS_RES_SENDFILE', 'EXPRESS_BODY_PARSER', 'NODE_NEW_BUFFER',
                          'NODE_CREATE_CIPHER', 'NODE_URL_PARSE', 'NODE_FS_EXISTS'})
        self.assertEqual({h['status'] for h in data['deprecations']}, {'deprecated'})
        self.assertEqual(next(p['installed'] for p in data['dependencies'] if p['name'] == 'express'), '4.22.1')
        self.assertEqual({c['kind'] for c in data['commands']}, {'start', 'seed'})

    def test_flask_programmatic_rules_keep_all_registered_methods(self):
        self.put('app.py', 'from flask import Flask\napp=Flask(__name__)\n'
                 'app.add_url_rule("/users", "users", users, methods=["GET", "POST"])\n'
                 'app.add_url_rule("/health", view_func=health)\n')
        endpoints = self.inventory()['endpoints']
        self.assertEqual([(e['method'], e['path'], e['line']) for e in endpoints],
                         [('GET', '/users', 3), ('POST', '/users', 3), ('GET', '/health', 4)])

    def test_phase1_summary_is_portuguese_and_keeps_machine_output_default(self):
        self.put('app.py', 'from flask import Flask\napp=Flask(__name__)\n')
        result = self.run_cli('--summary')
        self.assertEqual(result.returncode, 0, result.stderr)
        for label in ['FASE 1: ANÁLISE DO PROJETO', 'Linguagem:', 'Framework:',
                      'Dependências:', 'Domínio:', 'Arquitetura:', 'Arquivos:',
                      'Banco de dados:', 'Endpoints:']:
            self.assertIn(label, result.stdout)
        self.assertIn('1 arquivos de código, 2 linhas', result.stdout)
        self.assertNotIn('FASE 1:', self.run_cli().stdout)

    def test_empty_project_bad_input_and_source_symlinks(self):
        self.assertEqual(self.inventory()['files'], [])
        outside = self.root.parent / (self.root.name + '-outside.py')
        outside.write_text('password="' + CANARY + '"\n', encoding='utf-8')
        self.addCleanup(outside.unlink)
        (self.root / 'linked.py').symlink_to(outside)
        self.put('broken.py', 'this is not valid Python (\n')
        self.assertEqual(len(self.inventory()['files']), 1)
        self.assertEqual(self.inventory()['endpoints'], [])
        result = self.run_cli('--project-root', self.root / 'missing')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(list(self.root.rglob('*.pyc')))

    def test_declared_frameworks_pyproject_and_invalid_manifest_shapes(self):
        self.put('pyproject.toml', '[project]\ndependencies = ["Flask>=3.0", "SQLAlchemy==2.0.9"]\n')
        data = self.inventory()
        self.assertEqual(data['framework'], 'Flask')
        self.assertEqual(next(p['declared'] for p in data['dependencies'] if p['name'] == 'Flask'), '>=3.0')
        self.put('package.json', '{"dependencies": [], "engines": [], "scripts": []}')
        self.assertEqual(self.run_cli('--json').returncode, 0)
        self.put('package.json', 'not-json')
        self.assertEqual(self.run_cli('--json').returncode, 0)

    def test_explicit_table_names_sqlite_uris_and_non_python_languages(self):
        self.put('models.py', 'class Item(Base):\n    __tablename__ = "items"\n'
                 'DATABASE_URI="sqlite:///instance/store.sqlite"\n')
        self.put('main.go', 'package main\nfunc main() {}\n')
        data = self.inventory()
        self.assertEqual(data['language'], 'Go, Python')
        self.assertEqual({t['name'] for t in data['tables']}, {'items'})
        self.assertEqual([d['path'] for d in data['data_stores']], ['instance/store.sqlite'])

    def test_nested_blueprints_and_relative_module_imports(self):
        self.put('routes/__init__.py', '')
        self.put('routes/child.py', 'from flask import Blueprint\n'
                 'bp=Blueprint("child", __name__, url_prefix="/child")\n'
                 '@bp.route("/thing")\ndef thing(): pass\n')
        self.put('routes/parent.py', 'from flask import Blueprint\nfrom .child import bp\n'
                 'parent=Blueprint("parent", __name__, url_prefix="/parent")\n'
                 'parent.register_blueprint(bp)\n')
        self.put('app.py', 'from flask import Flask\nfrom routes.parent import parent\n'
                 'app=Flask(__name__)\napp.register_blueprint(parent, url_prefix="/api")\n')
        self.assertEqual([e['path'] for e in self.inventory()['endpoints']], ['/api/child/thing'])

    def test_inventory_never_executes_project_or_readme_commands(self):
        self.put('app.py', 'from pathlib import Path\nPath("EXECUTED").write_text("bad")\n'
                 '@app.route("/safe")\ndef safe(): return "ok"\n')
        self.put('README.md', '```sh\npython app.py --smtp_pass ' + CANARY + '\n```\n')
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'EXECUTED').exists())
        self.assertFalse((SCRIPT.parent.parent / 'EXECUTED').exists())

    def test_node_installed_metadata_is_used_even_without_manifest(self):
        self.put('app.js', 'const express=require("express");\nreq.param("id");\n')
        self.put('node_modules/express/package.json', '{"name":"express","version":"4.22.1"}')
        data = self.inventory()
        self.assertEqual(data['deprecations'][0]['status'], 'deprecated')
        self.assertEqual(data['deprecations'][0]['version'], '4.22.1')

    def test_blueprint_module_import_resolves_package_children(self):
        self.put('routes/__init__.py', '')
        self.put('routes/users.py', 'from flask import Blueprint\n'
                 'bp=Blueprint("users",__name__,url_prefix="/users")\n'
                 '@bp.route("/all")\ndef all_users(): pass\n')
        self.put('app.py', 'from flask import Flask\nfrom routes import users\n'
                 'app=Flask(__name__)\napp.register_blueprint(users.bp, url_prefix="/api")\n')
        self.assertEqual([e['path'] for e in self.inventory()['endpoints']], ['/api/all'])

    def test_uv_pyvenv_version_info_resolves_python_runtime(self):
        # O uv grava "version_info" no pyvenv.cfg, não "version".
        self.put('app.py', 'from datetime import datetime\ndatetime.utcnow()\n')
        self.put('.venv/pyvenv.cfg', 'home = /opt/python/bin\nimplementation = CPython\n'
                 'uv = 0.13.1\nversion_info = 3.14.4\ninclude-system-site-packages = false\n')
        data = self.inventory()
        self.assertEqual(data['runtime']['python'], '3.14.4')
        self.assertEqual({h['status'] for h in data['deprecations']}, {'deprecated'})
        self.assertNotIn('/opt/python', self.run_cli().stdout)

    def test_node_lists_only_direct_dependencies_when_manifest_exists(self):
        self.put('app.js', 'const express=require(\"express\");\n')
        self.put('package.json', '{\"dependencies\":{\"express\":\"^4.18.2\"},'
                 '\"devDependencies\":{\"nodemon\":\"^3.0.0\"}}')
        self.put('node_modules/express/package.json', '{\"name\":\"express\",\"version\":\"4.22.1\"}')
        self.put('node_modules/accepts/package.json', '{\"name\":\"accepts\",\"version\":\"1.3.8\"}')
        self.put('node_modules/@scope/inner/package.json', '{\"name\":\"@scope/inner\",\"version\":\"1.0.0\"}')
        names = {p['name'] for p in self.inventory()['dependencies']}
        self.assertEqual(names, {'express', 'nodemon'})
        output = self.run_cli().stdout
        self.assertNotIn('accepts', output)
        self.assertNotIn('RUNTIME python', output)

    def test_python_lists_direct_dependencies_but_resolves_transitive_versions(self):
        self.put('app.py', 'from flask import Flask\napp = Flask(__name__)\nUser.query.get(1)\n')
        self.put('requirements.txt', 'Flask==3.0.0\nFlask-SQLAlchemy==3.1.1\n')
        self.put('.venv/pyvenv.cfg', 'version_info = 3.14.4\n')
        site = '.venv/lib/python3.14/site-packages/'
        for name, version in [('Flask', '3.0.0'), ('Flask-SQLAlchemy', '3.1.1'), ('SQLAlchemy', '2.1.5'),
                              ('blinker', '1.9.0')]:
            self.put(site + name.lower() + '-' + version + '.dist-info/METADATA',
                     'Name: {}\nVersion: {}\n'.format(name, version))
        data = self.inventory()
        self.assertEqual({p['name'].lower(): p['installed'] for p in data['dependencies']},
                         {'flask': '3.0.0', 'flask-sqlalchemy': '3.1.1'})
        self.assertEqual({h['status'] for h in data['deprecations'] if h['rule'] == 'SA_QUERY_GET'}, {'deprecated'})
        output = self.run_cli().stdout
        self.assertNotIn('blinker', output)
        self.assertNotIn('DEPENDENCY SQLAlchemy', output)
        summary = self.run_cli('--summary').stdout
        self.assertIn('Linguagem:      Python 3.14.4\n', summary)
        self.assertIn('Framework:      Flask 3.0.0\n', summary)
        self.assertIn('Dependências:   Flask 3.0.0, Flask-SQLAlchemy 3.1.1\n', summary)

    def test_node_summary_shows_installed_framework_version(self):
        self.put('src/app.js', 'const express = require("express");\nconst app = express();\n'
                 'app.get("/x", (req, res) => res.send("x"));\n')
        self.put('package.json', '{"dependencies":{"express":"^4.18.2","sqlite3":"^5.1.6"}}')
        self.put('node_modules/express/package.json', '{"name":"express","version":"4.22.1"}')
        summary = self.run_cli('--summary').stdout
        self.assertIn('Linguagem:      JavaScript (Node.js)\n', summary)
        self.assertIn('Framework:      Express 4.22.1\n', summary)
        self.assertIn('Dependências:   express 4.22.1, sqlite3 ^5.1.6 (declarada)\n', summary)

    def test_install_commands_are_not_start_commands(self):
        self.put('app.js', 'const express=require(\"express\");\n')
        self.put('README.md', '```sh\nnpm install\nnpm ci\npython -m pip install -r requirements.txt\n'
                 'npm start\n```\n')
        kinds = {c['command']: c['kind'] for c in self.inventory()['commands']}
        self.assertEqual(kinds['npm install'], 'install')
        self.assertEqual(kinds['npm ci'], 'install')
        self.assertEqual(kinds['python -m pip install -r requirements.txt'], 'install')
        self.assertEqual(kinds['npm start'], 'start')


if __name__ == '__main__':
    unittest.main(verbosity=2)
