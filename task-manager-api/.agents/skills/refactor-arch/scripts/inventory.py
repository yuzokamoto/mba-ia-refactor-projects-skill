"""Inventário estático e determinístico; nunca importa nem executa o projeto."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import json
import os
from pathlib import Path
import re

SENSITIVE_COMMAND_RE = re.compile(r'password|passwd|senha|secret|token|api[_-]?key|private|credential|smtp[_-]?pass|card|cart[aã]o|(?:\b|_)key(?:\b|_)|://[^/\s]+:[^/\s]+@', re.I)

EXCLUDED = {'.venv', 'venv', 'node_modules', '.git', '__pycache__', '.agents',
            '.claude', 'dist', 'build', 'instance'}
EXTENSIONS = {'.py': 'Python', '.js': 'JavaScript', '.mjs': 'JavaScript',
              '.cjs': 'JavaScript', '.ts': 'TypeScript', '.tsx': 'TypeScript',
              '.jsx': 'JavaScript', '.java': 'Java', '.go': 'Go', '.rs': 'Rust',
              '.rb': 'Ruby', '.php': 'PHP', '.cs': 'C#', '.kt': 'Kotlin',
              '.c': 'C', '.h': 'C', '.cpp': 'C++', '.swift': 'Swift'}


def project_files(root):
    """Lista arquivos sem atravessar links simbólicos ou diretórios gerados."""
    result = []
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                and not Path(base, d).is_symlink())
        for name in sorted(files):
            path = Path(base, name)
            if not path.is_symlink() and path.suffix.lower() in EXTENSIONS:
                result.append(path)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix())


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return default


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def join_route(prefix, path):
    return prefix.rstrip('/') + '/' + path.lstrip('/') if prefix else path


def python_routes(sources):
    """Resolve receptores e registros de blueprints sem importar módulos."""
    trees, modules, aliases, objects, registrations = {}, {}, {}, {}, {}
    entries, routes = [], []
    for file, text in sources.items():
        if not file.endswith('.py'):
            continue
        try:
            trees[file] = ast.parse(text)
        except SyntaxError:
            continue
        module = file[:-3].replace('/', '.')
        modules[module.removesuffix('.__init__')] = file
    for file, tree in trees.items():
        package = file.split('/')[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                parts = package[:len(package) - node.level + 1] if node.level else []
                if node.module:
                    parts += node.module.split('.')
                module = '.'.join(parts)
                for alias in node.names:
                    target = modules.get(module)
                    child = modules.get(module + '.' + alias.name)
                    if child:
                        aliases[(file, alias.asname or alias.name)] = (child, '')
                    elif target:
                        aliases[(file, alias.asname or alias.name)] = (target, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        aliases[(file, alias.asname or alias.name)] = (modules[alias.name], '')
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                kind = dotted(node.value.func).split('.')[-1]
                if kind not in {'Flask', 'Blueprint'}:
                    continue
                prefix = next((literal(k.value, '') for k in node.value.keywords
                               if k.arg == 'url_prefix'), '')
                for target in node.targets:
                    objects[(file, dotted(target))] = prefix if isinstance(prefix, str) else ''
                if kind == 'Flask':
                    entries.append({'file': file, 'line': node.lineno})

    def resolve(file, name):
        seen = set()
        while (file, name) not in seen:
            seen.add((file, name))
            if (file, name) in aliases:
                file, name = aliases[(file, name)]
            elif '.' in name and (file, name.split('.')[0]) in aliases:
                head, tail = name.split('.', 1)
                file, original = aliases[(file, head)]
                name = original + '.' + tail if original else tail
            else:
                break
        return file, name

    for file, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'add_url_rule' and node.args:
                    path = literal(node.args[0])
                    methods = next((literal(k.value, []) for k in node.keywords
                                    if k.arg == 'methods'), ['GET'])
                    if isinstance(path, str) and isinstance(methods, (list, tuple, set)):
                        owner = resolve(file, dotted(node.func.value))
                        for method in sorted(set(m for m in methods if isinstance(m, str))):
                            routes.append((owner, {'method': method.upper(), 'path': path,
                                                  'file': file, 'line': node.lineno}))
                if node.func.attr == 'register_blueprint' and node.args:
                    child = resolve(file, dotted(node.args[0]))
                    parent = resolve(file, dotted(node.func.value))
                    override = next((literal(k.value) for k in node.keywords
                                     if k.arg == 'url_prefix'), None)
                    prefix = override if isinstance(override, str) else objects.get(child, '')
                    registrations.setdefault(child, []).append((parent, prefix))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                if not isinstance(decorator.func, ast.Attribute):
                    continue
                name = decorator.func.attr
                if name not in {'route', 'get', 'post', 'put', 'patch', 'delete'}:
                    continue
                path = literal(decorator.args[0])
                if not isinstance(path, str):
                    continue
                owner = resolve(file, dotted(decorator.func.value))
                methods = ['GET'] if name == 'route' else [name.upper()]
                for keyword in decorator.keywords:
                    if keyword.arg == 'methods':
                        methods = literal(keyword.value, [])
                if not isinstance(methods, (list, tuple, set)):
                    continue
                for method in sorted(set(m for m in methods if isinstance(m, str))):
                    routes.append((owner, {'method': method.upper(), 'path': path,
                                          'file': file, 'line': decorator.lineno}))

    def prefixes(owner, seen):
        if owner in seen:
            return []
        if owner not in registrations:
            return [objects.get(owner, '')]
        return [join_route(base, prefix) if prefix else base
                for parent, prefix in registrations[owner]
                for base in prefixes(parent, seen | {owner})]

    endpoints = []
    for owner, route in routes:
        for prefix in sorted(set(prefixes(owner, set()))):
            endpoints.append(dict(route, path=join_route(prefix, route['path'])))
    return sorted(endpoints, key=lambda e: (e['file'], e['line'], e['method'], e['path'])), entries


JS_TOKEN_RE = re.compile(
    r'''//[^\n]*|/\*[\s\S]*?\*/|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|[A-Za-z_$][\w$]*|\d+|[^\s]''')


def js_tokens(text):
    """Ignora comentários, preservando offsets e literais de JavaScript."""
    return [(m.group(), m.start(), bool(m.group('string'))) for m in JS_TOKEN_RE.finditer(text)
            if not m.group().startswith(('//', '/*'))]


def js_string(token):
    if not token[2] or '${' in token[0]:
        return None
    try:
        return ast.literal_eval(token[0]) if token[0][0] != '`' else token[0][1:-1]
    except (SyntaxError, ValueError):
        return None


def javascript_routes(sources):
    """Reconhece rotas e montagens locais CommonJS/ESM por análise lexical."""
    tokens = {file: js_tokens(text) for file, text in sources.items()
              if Path(file).suffix in {'.js', '.mjs', '.cjs', '.ts', '.jsx', '.tsx'}}
    objects, aliases, exports, mounts, routes, entries = set(), {}, {}, {}, [], []

    def receiver(items, index):
        start = index
        while start >= 2 and items[start - 1][0] == '.' and re.fullmatch(r'[\w$]+', items[start - 2][0]):
            start -= 2
        return ''.join(t[0] for t in items[start:index + 1])

    def module_path(file, name):
        if not name or not name.startswith('.'):
            return None
        base = os.path.normpath(str(Path(file).parent / name)).replace(os.sep, '/')
        return next((candidate for candidate in [base] + [base + ext for ext in
                    ('.js', '.mjs', '.cjs', '.ts', '/index.js', '/index.mjs')]
                     if candidate in tokens), None)

    for file, items in tokens.items():
        values = [t[0] for t in items]
        for i in range(len(items)):
            if values[i:i + 3] == ['=', 'express', '('] or values[i:i + 5] == ['=', 'express', '.', 'Router', '(']:
                if i:
                    name = receiver(items, i - 1)
                    objects.add((file, name))
                    if values[i:i + 3] == ['=', 'express', '(']:
                        entries.append({'file': file, 'line': sources[file].count('\n', 0, items[i][1]) + 1})
            if values[i:i + 2] == ['require', '('] and i + 3 < len(items):
                if i >= 2 and values[i - 1] == '=':
                    target = module_path(file, js_string(items[i + 2]))
                    if target:
                        aliases[(file, receiver(items, i - 2))] = (target, 'default')
            if values[i] == 'import' and i + 3 < len(items):
                end = next((j for j in range(i + 1, min(i + 30, len(items))) if values[j] == 'from'), None)
                if end is not None and end + 1 < len(items):
                    target = module_path(file, js_string(items[end + 1]))
                    if target and values[i + 1] != '{':
                        aliases[(file, values[i + 1])] = (target, 'default')
                    elif target:
                        for j in range(i + 2, end):
                            if values[j] not in {'{', '}', ',', 'as'} and (j == i + 2 or values[j - 1] == ','):
                                local = values[j + 2] if values[j + 1:j + 2] == ['as'] else values[j]
                                aliases[(file, local)] = (target, values[j])
            if values[i:i + 4] == ['module', '.', 'exports', '='] and i + 4 < len(items):
                exports[(file, 'default')] = (file, values[i + 4])
            if values[i:i + 2] == ['export', 'default'] and i + 2 < len(items):
                exports[(file, 'default')] = (file, values[i + 2])
            if values[i:i + 2] == ['exports', '.'] and values[i + 3:i + 4] == ['='] and i + 4 < len(items):
                exports[(file, values[i + 2])] = (file, values[i + 4])

    def resolve(owner):
        seen = set()
        while owner not in seen:
            seen.add(owner)
            if owner in aliases:
                owner = exports.get(aliases[owner], aliases[owner])
            else:
                break
        return owner

    for file, items in tokens.items():
        values = [t[0] for t in items]
        for i in range(2, len(items) - 2):
            if values[i - 1] != '.' or values[i + 1] != '(':
                continue
            name, verb = receiver(items, i - 2), values[i]
            owner = resolve((file, name))
            if owner not in objects and name.split('.')[-1] not in {'app', 'router'}:
                continue
            path = js_string(items[i + 2])
            if verb in {'get', 'post', 'put', 'patch', 'delete', 'all', 'head', 'options'} and path is not None:
                routes.append((owner, {'method': verb.upper(), 'path': path, 'file': file,
                                       'line': sources[file].count('\n', 0, items[i - 2][1]) + 1}))
            if verb == 'use':
                start = i + 4 if path is not None and values[i + 3:i + 4] == [','] else i + 2
                if start < len(items) and re.fullmatch(r'[A-Za-z_$][\w$]*', values[start]):
                    child = resolve((file, values[start]))
                    if child in objects:
                        mounts.setdefault(child, []).append((owner, path or ''))

    def prefixes(owner, seen):
        if owner in seen:
            return []
        if owner not in mounts:
            return ['']
        return [join_route(base, prefix) if prefix else base for parent, prefix in mounts[owner]
                for base in prefixes(parent, seen | {owner})]

    endpoints = [dict(route, path=join_route(prefix, route['path']))
                 for owner, route in routes for prefix in sorted(set(prefixes(owner, set())))]
    return sorted(endpoints, key=lambda e: (e['file'], e['line'], e['method'], e['path'])), entries


def command_kind(command):
    """Instalação de dependências não é comando de start (pode exigir rede)."""
    if re.search(r'\b(?:install|ci|add)\b', command, re.I):
        return 'install'
    return 'seed' if re.search(r'seed|populate|init.db', command, re.I) else 'start'


def metadata(root):
    """Lê manifestos e versões instaladas sem consultar interpretadores."""
    manifests, packages, commands = [], {}, []
    runtime = {'python': 'unknown', 'node': 'unknown'}

    def package(name):
        key = re.sub(r'[-_.]+', '-', name).lower()
        return packages.setdefault(key, {'name': name, 'declared': 'unknown', 'installed': 'unknown'})

    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                and not Path(base, d).is_symlink())
        for name in sorted(files):
            path = Path(base, name)
            if path.is_symlink():
                continue
            file = path.relative_to(root).as_posix()
            if re.fullmatch(r'requirements[^/]*\.txt', name, re.IGNORECASE):
                manifests.append(file)
                for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                    match = re.match(r'^\s*([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*([^;#\s]*)', line)
                    if match:
                        package(match.group(1))['declared'] = match.group(2) or 'unconstrained'
            elif name == 'package.json':
                manifests.append(file)
                try:
                    info = json.loads(path.read_text(encoding='utf-8'))
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(info, dict):
                    continue
                for kind in ('dependencies', 'devDependencies', 'peerDependencies'):
                    dependencies = info.get(kind, {})
                    if not isinstance(dependencies, dict):
                        continue
                    for dependency, version in dependencies.items():
                        package(dependency)['declared'] = str(version)
                engines = info.get('engines', {})
                if isinstance(engines, dict):
                    runtime['node'] = str(engines.get('node', runtime['node']))
                scripts = info.get('scripts', {})
                for script, command in (scripts.items() if isinstance(scripts, dict) else []):
                    kind = 'seed' if re.search(r'seed|populate|init.db', script, re.I) else 'start'
                    if re.search(r'start|serve|dev|seed|populate|init.db', script, re.I):
                        if not SENSITIVE_COMMAND_RE.search(str(command)):
                            commands.append({'kind': kind, 'command': 'npm run ' + script,
                                             'file': file})
            elif name in {'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile',
                          'Gemfile', 'Cargo.toml', 'go.mod', 'pom.xml', 'composer.json'}:
                manifests.append(file)
                if name == 'pyproject.toml':
                    contents = path.read_text(encoding='utf-8', errors='replace')
                    for array in re.finditer(r'\bdependencies\s*=\s*\[([\s\S]*?)\]', contents):
                        for quoted in re.finditer(r'''["']([^"']+)["']''', array.group(1)):
                            requirement = re.match(r'([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(.*)', quoted.group(1))
                            if requirement:
                                package(requirement.group(1))['declared'] = requirement.group(2) or 'unconstrained'
                    poetry = re.search(r'\[tool\.poetry\.dependencies\]([^\[]*)', contents)
                    if poetry:
                        for requirement in re.finditer(r'''^([\w.-]+)\s*=\s*["']([^"']+)["']''', poetry.group(1), re.MULTILINE):
                            if requirement.group(1) != 'python':
                                package(requirement.group(1))['declared'] = requirement.group(2)
            if name.lower().startswith('readme'):
                for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    command = line.strip().lstrip('$ ').strip('`')
                    if not re.match(r'^(?:python[\d.]*|flask|node|npm|yarn|pnpm)\s+', command):
                        continue
                    if SENSITIVE_COMMAND_RE.search(command):
                        continue
                    commands.append({'kind': command_kind(command), 'command': command, 'file': file,
                                     'line': number})
    # Com manifesto Python, só as dependências declaradas são listadas; as transitivas ficam em
    # 'installed' para resolver versões (ex.: SQLAlchemy sob Flask-SQLAlchemy nas regras de deprecação).
    python_declared = {key for key, info in packages.items() if info['declared'] != 'unknown'}
    has_python_manifest = any(Path(m).name.lower().startswith('requirements') or Path(m).name in
                              {'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile'} for m in manifests)
    installed_versions = {}
    for environment in (root / '.venv', root / 'venv'):
        config = environment / 'pyvenv.cfg'
        if config.is_file() and not config.is_symlink():
            # O uv grava "version_info"; o venv padrão grava "version".
            match = re.search(r'^version(?:_info)?\s*=\s*([^\n]+)', config.read_text(encoding='utf-8'),
                              re.MULTILINE | re.I)
            if match:
                runtime['python'] = match.group(1).strip()
        for path in sorted(environment.glob('lib/python*/site-packages/*.dist-info/METADATA')):
            if path.is_symlink():
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            name = re.search(r'^Name:[ \t]*(\S+)', text, re.MULTILINE)
            version = re.search(r'^Version:[ \t]*(\S+)', text, re.MULTILINE)
            if name and version:
                key = re.sub(r'[-_.]+', '-', name.group(1)).lower()
                installed_versions[key] = version.group(1)
                if not has_python_manifest or key in python_declared:
                    package(name.group(1))['installed'] = version.group(1)
    node_modules = root / 'node_modules'
    # Com package.json, só as dependências diretas interessam; as transitivas poluem a Fase 1.
    has_manifest = (root / 'package.json').is_file()
    installed = [] if has_manifest else (list(node_modules.glob('*/package.json'))
                                         + list(node_modules.glob('@*/*/package.json')))
    for path in sorted(installed):
        if not path.is_symlink() and not path.parent.is_symlink():
            package(path.parent.relative_to(node_modules).as_posix())
    for info in list(packages.values()):
        name = info['name']
        if '..' in name.split('/') or name.startswith('/'):
            continue
        path = root / 'node_modules' / name / 'package.json'
        if path.is_file() and not path.is_symlink():
            try:
                version = json.loads(path.read_text(encoding='utf-8')).get('version')
                if isinstance(version, str):
                    info['installed'] = version
            except (ValueError, UnicodeError, AttributeError):
                pass
    for key, info in packages.items():
        if info['installed'] != 'unknown':
            installed_versions.setdefault(key, info['installed'])
    return {'manifests': sorted(manifests), 'dependencies': sorted(packages.values(), key=lambda p: p['name'].lower()),
            'runtime': runtime, 'commands': commands, 'installed': installed_versions}


def stores_and_tables(root, sources):
    """Localiza bancos e tabelas sem abrir nenhum banco de dados."""
    stores, tables = {}, []
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED - {'instance'}
                                and not Path(base, d).is_symlink())
        for name in sorted(files):
            path = Path(base, name)
            if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3'} and not path.is_symlink():
                key = path.relative_to(root).as_posix()
                stores[key] = {'path': key, 'kind': 'sqlite', 'exists': True}
    for file, text in sources.items():
        strings = []
        if file.endswith('.py'):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = ast.Module(body=[], type_ignores=[])
            strings = [(node.value, node.lineno) for node in ast.walk(tree)
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            for assignment in ast.walk(tree):
                if isinstance(assignment, ast.Assign) and any(dotted(target) == '__tablename__' for target in assignment.targets):
                    name = literal(assignment.value)
                    if isinstance(name, str):
                        tables.append({'name': name, 'file': file, 'line': assignment.lineno})
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or not any(dotted(base).endswith('.Model') for base in node.bases):
                    continue
                explicit = next((child for child in node.body if isinstance(child, ast.Assign)
                                 and any(dotted(target) == '__tablename__' for target in child.targets)), None)
                name = literal(explicit.value) if explicit else node.name.lower()
                if isinstance(name, str):
                    tables.append({'name': name, 'file': file, 'line': explicit.lineno if explicit else node.lineno})
        elif Path(file).suffix in {'.js', '.mjs', '.cjs', '.ts'}:
            strings = [(js_string(token), text.count('\n', 0, token[1]) + 1)
                       for token in js_tokens(text) if token[2]]
        for value, line in strings:
            if not value:
                continue
            if re.fullmatch(r'(?:sqlite:///)?[^\n\x00]+\.(?:db|sqlite|sqlite3)', value):
                path = value.removeprefix('sqlite:///')
                stores.setdefault(path, {'path': path, 'kind': 'sqlite', 'exists': False})
            for match in re.finditer(r'\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?([\w]+)', value, re.I):
                tables.append({'name': match.group(1), 'file': file,
                               'line': line + value.count('\n', 0, match.start())})
    unique = {(t['name'], t['file'], t['line']): t for t in tables}
    return [stores[key] for key in sorted(stores)], [unique[key] for key in sorted(unique)]


# As condições são dados explícitos; versões declaradas não substituem instalações.
DEPRECATION_RULES = (
    ('PY_DATETIME_UTCNOW', 'python', 'python', (3, 12, 0), r'(?:datetime\.)+utcnow$', 'call', 'MEDIUM'),
    ('PY_DATETIME_UTCFROMTIMESTAMP', 'python', 'python', (3, 12, 0), r'(?:datetime\.)+utcfromtimestamp$', 'call', 'MEDIUM'),
    ('SA_QUERY_GET', 'python', 'sqlalchemy', (2, 0, 0), r'\.query\.get$', 'call', 'MEDIUM'),
    ('SA_QUERY_GET_OR_404', 'python', 'sqlalchemy', (2, 0, 0), r'\.query\.get_or_404$', 'call', 'MEDIUM'),
    ('SA_SESSION_QUERY', 'python', 'sqlalchemy', (2, 0, 0), r'(?:^|\.)session\.query$', 'call', 'INFO'),
    ('FLASK_BEFORE_FIRST_REQUEST', 'python', 'flask', (2, 3, 0), r'\.before_first_request$', 'reference', 'HIGH'),
    ('FLASK_JSON_ENCODER', 'python', 'flask', (2, 2, 0), r'^flask\.json\.JSONEncoder$', 'reference', 'MEDIUM'),
    ('EXPRESS_RES_SEND_STATUS_BODY', 'javascript', 'express', (4, 7, 0), r'\bres\s*\.\s*send\s*\(\s*(?:\d+|[\w$]+)\s*,', 'regex', 'MEDIUM'),
    ('EXPRESS_REQ_PARAM', 'javascript', 'express', (4, 11, 0), r'\breq\s*\.\s*param\s*\(', 'regex', 'MEDIUM'),
    ('EXPRESS_RES_SENDFILE', 'javascript', 'express', (4, 8, 0), r'\bres\s*\.\s*sendfile\s*\(', 'regex', 'MEDIUM'),
    ('EXPRESS_BODY_PARSER', 'javascript', 'express', (4, 0, 0), r'(?<![\w$.])bodyParser\s*\(', 'regex', 'MEDIUM'),
    ('NODE_NEW_BUFFER', 'javascript', 'node', (6, 0, 0), r'\bnew\s+Buffer\s*\(', 'regex', 'MEDIUM'),
    ('NODE_CREATE_CIPHER', 'javascript', 'node', (10, 0, 0), r'\bcrypto\s*\.\s*createCipher\s*\(', 'regex', 'MEDIUM'),
    ('NODE_URL_PARSE', 'javascript', 'node', (11, 0, 0), r'\burl\s*\.\s*parse\s*\(', 'regex', 'MEDIUM'),
    ('NODE_FS_EXISTS', 'javascript', 'node', (1, 0, 0), r'\bfs\s*\.\s*exists\s*\(', 'regex', 'MEDIUM'),
)
URL_DEPRECATED_RANGES = (((11, 0, 0), (14, 17, 0)), ((15, 0, 0), (15, 13, 0)),
                         ((18, 13, 0), None))


def version_status(version, minimum, rule):
    """Retorna desconhecido quando o intervalo declarado não prova a condição."""
    match = re.fullmatch(r'\s*(>=)?v?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*', version)
    if not match:
        return 'version-unknown'
    value = tuple(int(part or 0) for part in match.groups()[1:])
    if match.group(1):
        limit = (18, 13, 0) if rule == 'NODE_URL_PARSE' else minimum
        return 'deprecated' if value >= limit else 'version-unknown'
    if rule == 'NODE_URL_PARSE':
        applies = any(value >= low and (high is None or value < high)
                      for low, high in URL_DEPRECATED_RANGES)
    else:
        applies = value >= minimum
    return 'deprecated' if applies else None


def deprecated_hits(sources, details):
    """Aplica regras somente a chamadas/referências, nunca a comentários."""
    versions = dict(details.get('installed', {}))
    versions.update({re.sub(r'[-_.]+', '-', p['name']).lower(): p['installed']
                     for p in details['dependencies'] if p['installed'] != 'unknown'})
    versions.update(details['runtime'])
    found = {}
    for file, text in sources.items():
        candidates = []
        language = 'python' if file.endswith('.py') else 'javascript'
        if language == 'python':
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = (node.module or '') + '.' + alias.name
                        candidates.append(((node.module or '') + '.' + alias.name, node.lineno, 'reference'))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = alias.name
            for node in ast.walk(tree):
                kind = 'call' if isinstance(node, ast.Call) else 'reference'
                name = dotted(node.func) if isinstance(node, ast.Call) else dotted(node)
                if not name:
                    continue
                head, _, tail = name.partition('.')
                if head in aliases:
                    name = aliases[head] + ('.' + tail if tail else '')
                candidates.append((name, node.lineno, kind))
        else:
            if Path(file).suffix not in {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}:
                continue
            def mask(match):
                if match.group('string') or match.group().startswith(('//', '/*')):
                    return re.sub(r'[^\r\n]', ' ', match.group())
                return match.group()
            code = JS_TOKEN_RE.sub(mask, text)
        for rule, rule_language, package, minimum, pattern, mode, severity in DEPRECATION_RULES:
            if rule_language != language:
                continue
            version = versions.get(package, 'unknown')
            status = version_status(version, minimum, rule)
            if status is None:
                continue
            if mode == 'regex':
                lines = [text.count('\n', 0, m.start()) + 1 for m in re.finditer(pattern, code)]
            else:
                lines = [line for name, line, kind in candidates if (mode == 'reference' or kind == mode)
                         and re.search(pattern, name)]
            for line in lines:
                found[(file, line, rule)] = {'rule': rule, 'file': file, 'line': line,
                                              'status': status, 'severity': severity,
                                              'package': package, 'version': version,
                                              'minimum': '.'.join(map(str, minimum))}
    return [found[key] for key in sorted(found)]


def collect(root):
    files, languages, sources = [], {}, {}
    framework = 'unknown'
    for path in project_files(root):
        file = path.relative_to(root).as_posix()
        text = path.read_text(encoding='utf-8', errors='replace')
        sources[file] = text
        lines = len(text.splitlines())
        files.append({'path': file, 'lines': lines})
        language = EXTENSIONS[path.suffix.lower()]
        languages[language] = languages.get(language, 0) + 1
        if path.suffix == '.py':
            if re.search(r'\b(?:from\s+flask\b|import\s+flask\b)', text):
                framework = 'Flask'
    endpoints, entries = python_routes(sources)
    js_endpoints, js_entries = javascript_routes(sources)
    endpoints.extend(js_endpoints)
    entries.extend(js_entries)
    if js_endpoints or any('express' in text for file, text in sources.items()
                           if Path(file).suffix in {'.js', '.mjs', '.cjs'}):
        framework = 'Express' if framework == 'unknown' else framework + ', Express'
    stores, tables = stores_and_tables(root, sources)
    details = metadata(root)
    detected = set(framework.split(', ')) - {'unknown'}
    known = {'flask': 'Flask', 'express': 'Express', 'django': 'Django', 'fastapi': 'FastAPI'}
    for package in details['dependencies']:
        if package['name'].lower() in known and package['declared'] != 'unknown':
            detected.add(known[package['name'].lower()])
    framework = ', '.join(sorted(detected)) or 'unknown'
    return dict(details, **{'language': ', '.join(sorted(languages)) or 'unknown',
            'languages': languages, 'framework': framework, 'files': files,
            'loc': sum(f['lines'] for f in files), 'endpoints': endpoints,
            'data_stores': stores, 'tables': tables, 'deprecations': deprecated_hits(sources, details),
            'entry_points': entries})


def print_inventory(data):
    for key in ('language', 'framework', 'files', 'loc', 'endpoints',
                'data_stores', 'deprecations'):
        value = data[key]
        print('{}={}'.format(key.upper(), len(value) if isinstance(value, list) else value))
    for file in data['files']:
        print('FILE {path} {lines}'.format(**file))
    for endpoint in data['endpoints']:
        print('ENDPOINT {method} {path} {file}:{line}'.format(**endpoint))
    for hit in data['deprecations']:
        print('DEPRECATED {rule} {file}:{line} status={status} severity={severity}'.format(**hit))
    for table in data['tables']:
        print('TABLE {name} {file}:{line}'.format(**table))
    for dependency in data['dependencies']:
        print('DEPENDENCY {name} declared={declared} installed={installed}'.format(**dependency))
    present = {'python': 'Python' in data['languages'],
               'node': bool({'JavaScript', 'TypeScript'} & set(data['languages']))}
    for runtime, version in sorted(data['runtime'].items()):
        if present.get(runtime, True):
            print('RUNTIME {} {}'.format(runtime, version))
    for entry in data['entry_points']:
        print('ENTRY {file}:{line}'.format(**entry))
    for command in data['commands']:
        print('COMMAND {kind} {command}'.format(**command))


def dependency_label(package):
    """Versão instalada; sem metadados instalados, a restrição declarada marcada como tal."""
    if package['installed'] != 'unknown':
        return '{} {}'.format(package['name'], package['installed'])
    if package['declared'] not in ('unknown', 'unconstrained'):
        return '{} {} (declarada)'.format(package['name'], package['declared'])
    return package['name']


def summary_language(data):
    labels = []
    for language in sorted(data['languages']):
        if language == 'Python' and data['runtime'].get('python', 'unknown') != 'unknown':
            labels.append('Python ' + data['runtime']['python'])
        elif language in ('JavaScript', 'TypeScript'):
            node = data['runtime'].get('node', 'unknown')
            labels.append('{} (Node.js{})'.format(language, '' if node == 'unknown' else ' ' + node))
        else:
            labels.append(language)
    return ', '.join(labels) or 'unknown'


def summary_framework(data):
    versions = {p['name'].lower(): p['installed'] for p in data['dependencies']}
    versions.update({key: value for key, value in data.get('installed', {}).items() if key not in versions})
    labels = []
    for framework in data['framework'].split(', '):
        version = versions.get(framework.lower(), 'unknown')
        labels.append(framework if version == 'unknown' else framework + ' ' + version)
    return ', '.join(labels)


def print_summary(data):
    """O bloco humano não afirma domínio nem arquitetura sem análise."""
    print('================================')
    print('FASE 1: ANÁLISE DO PROJETO')
    print('================================')
    print('Linguagem:      ' + summary_language(data))
    print('Framework:      ' + summary_framework(data))
    print('Dependências:   ' + (', '.join(dependency_label(p) for p in data['dependencies'])
                                or 'nenhuma detectada'))
    print('Domínio:        a analisar')
    print('Arquitetura:    a analisar')
    print('Arquivos:       {} arquivos de código, {} linhas'.format(len(data['files']), data['loc']))
    print('Banco de dados: ' + (', '.join(s['path'] for s in data['data_stores']) or 'nenhum detectado'))
    print('Endpoints:      ' + str(len(data['endpoints'])))
    print('================================')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--json', action='store_true')
    output.add_argument('--summary', action='store_true')
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if not root.is_dir():
        parser.error('project root must be a directory')
    try:
        data = collect(root)
    except OSError:
        print('ERROR=unreadable-project', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
    elif args.summary:
        print_summary(data)
    else:
        print_inventory(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
