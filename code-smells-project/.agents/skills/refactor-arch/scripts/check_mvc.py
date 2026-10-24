"""Verifica limites MVC por análise estática, sem executar código do projeto."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import importlib.util
import io
import tokenize
import json
import os
from pathlib import Path
import re

EXCLUDED = {'.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__', '.agents',
            '.claude', 'tests', 'test', '__tests__', 'reports', 'instance', 'dist',
            'build', 'coverage', '.handoff', '.worktrees'}
EXTENSIONS = {'.py', '.js', '.mjs', '.cjs', '.ts'}
LAYER_NAMES = {
    'routes': {'route', 'routes', 'view', 'views', 'router', 'routers'},
    'controllers': {'controller', 'controllers'},
    'middlewares': {'middleware', 'middlewares'},
    'validators': {'validator', 'validators', 'schema', 'schemas', 'serializer',
                   'serializers', 'validation'},
    'models': {'model', 'models', 'repository', 'repositories', 'dao'},
    'services': {'service', 'services'},
    'config': {'config', 'configs', 'setting', 'settings'},
    'errors': {'error', 'errors', 'exception', 'exceptions'},
}
ENTRY_NAMES = {'app.py', 'main.py', 'wsgi.py', 'server.js', 'index.js', 'app.js'}


def load_helper(name):
    """Carrega somente o auxiliar confiável que acompanha este script."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY = load_helper('inventory')


def layer_of(file):
    """Classifica diretórios e sufixos, inclusive nomes em CamelCase."""
    path = Path(file)
    for part in list(path.parts[:-1]) + [path.stem]:
        split = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', part).lower()
        suffix = re.split(r'[^a-z0-9]+', split)[-1]
        for layer, names in LAYER_NAMES.items():
            if split in names or suffix in names or any(split.endswith(name) for name in names):
                return layer
    if path.name.lower() in ENTRY_NAMES and path.parent.as_posix().lower() in {'.', 'src'}:
        return 'entry'
    return 'other'


def project_sources(root):
    """Lê apenas fontes permitidas e nunca atravessa links simbólicos."""
    sources = {}
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                and not Path(base, d).is_symlink())
        for name in sorted(files):
            path = Path(base, name)
            if path.suffix.lower() in EXTENSIONS and not path.is_symlink():
                sources[path.relative_to(root).as_posix()] = path.read_text(encoding='utf-8')
    return dict(sorted(sources.items()))


HTTP_LAYERS = {'routes', 'controllers', 'validators', 'middlewares', 'entry'}
DOMAIN_LAYERS = {'models', 'services'}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
HTTP_NAMES = {'request', 'jsonify', 'make_response', 'abort', 'Response', 'g'}
VERBS = {'route', 'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}


def code_lines(text, tree):
    """Conta linhas com tokens, excluindo comentários e docstrings reais."""
    excluded = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef) + FUNCTIONS) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                excluded.update(range(first.lineno, first.end_lineno + 1))
    result = set()
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
               tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type not in ignored and token.string.strip():
            result.update(range(token.start[0], token.end[0] + 1))
    return result - excluded


def body_size(node, lines):
    """Desconsidera a assinatura e conta somente linhas do corpo da função."""
    start = max(node.lineno + 1, node.body[0].lineno)
    ignored = set()
    for child in ast.walk(node):
        if not isinstance(child, FUNCTIONS):
            continue
        ignored.update(range(child.lineno, max(child.lineno + 1, child.body[0].lineno)))
        for decorator in child.decorator_list:
            ignored.update(range(decorator.lineno, decorator.end_lineno + 1))
    return sum(start <= line <= node.end_lineno and line not in ignored for line in lines)


def imports_in(file, tree):
    """Resolve nomes importados estaticamente, inclusive imports relativos."""
    aliases, imports = {}, []
    package = file.split('/')[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split('.')[0]
                aliases[local] = alias.name if alias.asname else local
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            parts = package[:max(0, len(package) - node.level + 1)] if node.level else []
            if node.module:
                parts += node.module.split('.')
            module = '.'.join(parts)
            imports.append((module, node.lineno))
            for alias in node.names:
                name = module + '.' + alias.name if module else alias.name
                aliases[alias.asname or alias.name] = name
                imports.append((name, node.lineno))
    return aliases, imports


def canonical(name, aliases):
    """Expande apenas o primeiro segmento de um nome importado."""
    head, separator, tail = name.partition('.')
    return aliases.get(head, head) + (separator + tail if separator else '')


def data_import(name, modules, layers):
    """Reconhece nomes de persistência e módulos locais da camada de domínio."""
    if any(re.match(r'^(?:models?|services?|repositories|repository|database|db)$|^(?:models|services)',
                    part, re.I) for part in re.split(r'[./\\\\]+', name)):
        return True
    parts = name.split('.')
    return any(layers.get(modules.get('.'.join(parts[:end]))) in DOMAIN_LAYERS
               for end in range(1, len(parts) + 1))


def python_route(node):
    """Reconhece chamadas de definição de rota Flask com caminho literal."""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in VERBS | {'add_url_rule'} and bool(node.args)
            and isinstance(INVENTORY.literal(node.args[0]), str))


def direct_db(node, aliases):
    """Reconhece operações de persistência explicitadas no contrato."""
    name = canonical(INVENTORY.dotted(node), aliases)
    if isinstance(node, ast.Attribute):
        return (node.attr in {'query', 'cursor'} or name.endswith('db.session')
                or name.startswith('sqlite3.'))
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id == 'cursor'
    if isinstance(node, ast.Call):
        name = canonical(INVENTORY.dotted(node.func), aliases)
        return (name.split('.')[-1] in {'select', 'execute', 'executemany', 'executescript', 'cursor',
                                        'commit', 'rollback', 'get_db'}
                or name.startswith('sqlite3.'))
    return False


def status_literal(node):
    """Booleanos não são códigos HTTP, embora sejam inteiros em Python."""
    return isinstance(node, ast.Constant) and type(node.value) is int and 100 <= node.value <= 599


def analyze_python(file, tree, layer, lines, modules, layers, emit):
    """Aplica regras locais à AST e nunca carrega dependências do projeto."""
    aliases, imports = imports_in(file, tree)
    if layer == 'routes':
        for name, line in imports:
            if data_import(name, modules, layers):
                emit(file, line, 'routes_import_data')
    mappings = set()
    route_nodes = {id(dec) for function in ast.walk(tree) if isinstance(function, FUNCTIONS)
                   for dec in function.decorator_list if python_route(dec)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Dict):
                pairs = [(key, item) for key, item in zip(value.keys, value.values)
                         if isinstance(key, ast.Constant) and isinstance(key.value, str)
                         and isinstance(item, (ast.Name, ast.Attribute, ast.Lambda))]
                if len({key.value for key, _ in pairs}) >= 3:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    mappings.update(INVENTORY.dotted(target) for target in targets)
        is_route = (id(node) in route_nodes or
                    (python_route(node) and node.func.attr == 'add_url_rule'))
        if is_route and layer in DOMAIN_LAYERS | {'validators', 'other'}:
            emit(file, node.lineno, 'route_outside_http_layer')
        if isinstance(node, FUNCTIONS):
            decorated = any(python_route(dec) for dec in node.decorator_list)
            if (layer == 'routes' or decorated) and body_size(node, lines) > 8:
                emit(file, node.lineno, 'route_handler_too_long')
        if layer in HTTP_LAYERS and direct_db(node, aliases):
            emit(file, node.lineno, 'db_access_in_http_layer')
        if layer in DOMAIN_LAYERS:
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = canonical(INVENTORY.dotted(node), aliases)
                parts = name.split('.')
                if len(parts) > 1 and parts[0] in {'flask', 'werkzeug'} and parts[-1] in HTTP_NAMES:
                    emit(file, node.lineno, 'http_in_domain')
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
                value = node.value.elts[1]
                if status_literal(value):
                    emit(file, value.lineno, 'status_in_domain', value.col_offset + 1)
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg in {'status', 'status_code', 'code'} and status_literal(keyword.value):
                        emit(file, keyword.value.lineno, 'status_in_domain', keyword.value.col_offset + 1)
        if layer in {'routes', 'controllers'} and isinstance(node, ast.Call):
            name = INVENTORY.dotted(node.func).split('.')[-1]
            dispatch = (name in {'dispatch', 'handle', 'execute'} and bool(node.args)
                        and action_literal(INVENTORY.literal(node.args[0])))
            dynamic = (name == 'getattr' and len(node.args) >= 2
                       and not isinstance(node.args[1], ast.Constant))
            if dispatch or dynamic:
                emit(file, node.lineno, 'string_dispatch_controller')
    if layer in {'routes', 'controllers'}:
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and INVENTORY.dotted(node.value) in mappings:
                emit(file, node.lineno, 'string_dispatch_controller')
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == 'get' and INVENTORY.dotted(node.func.value) in mappings):
                emit(file, node.lineno, 'string_dispatch_controller')


ACTION_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_.:-]{0,63}')


def action_literal(value):
    """Nome de ação ('create_task', 'createTask'); SQL e palavras-chave em maiúsculas não contam."""
    return isinstance(value, str) and bool(ACTION_RE.fullmatch(value)) and not value.isupper()


def own_nodes(function):
    """Percorre o corpo sem atribuir retornos de funções internas à externa."""
    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, FUNCTIONS + (ast.ClassDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def python_helper_checks(trees, modules, layers, emit):
    """Propaga retornos de objetos persistentes entre funções e imports locais."""
    definitions, aliases_by_file = {}, {}
    for file, tree in trees.items():
        aliases_by_file[file] = imports_in(file, tree)[0]

        def visit(node, prefix=''):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, FUNCTIONS + (ast.ClassDef,)):
                    name = prefix + child.name
                    if isinstance(child, FUNCTIONS):
                        definitions[(file, name)] = child
                    visit(child, name + '.')
                else:
                    visit(child, prefix)
        visit(tree)

    def resolve(file, name, context='', seen=None):
        seen = set() if seen is None else seen
        if (file, name) in seen:
            return None
        seen.add((file, name))
        original = name
        name = canonical(name, aliases_by_file[file])
        if name.startswith(('self.', 'cls.')) and '.' in context:
            name = context.rsplit('.', 1)[0] + '.' + name.split('.', 1)[1]
        if (file, name) in definitions:
            return file, name
        if '.' in context and original == name:
            candidate = context.rsplit('.', 1)[0] + '.' + name
            if (file, candidate) in definitions:
                return file, candidate
        parts = name.split('.')
        for end in range(len(parts), 0, -1):
            target = modules.get('.'.join(parts[:end]))
            symbol = '.'.join(parts[end:])
            if target and (target, symbol) in definitions:
                return target, symbol
            if target and symbol.split('.')[0] in aliases_by_file.get(target, {}):
                resolved = resolve(target, symbol, seen=seen)
                if resolved:
                    return resolved
        return None

    tainted = set()

    def is_object(value, file, variables, context):
        if value is None:
            return False
        if isinstance(value, ast.Await):
            return is_object(value.value, file, variables, context)
        if isinstance(value, ast.Name):
            return value.id in variables or value.id in {'connection', 'conn', 'cursor'}
        if isinstance(value, ast.Attribute):
            name = canonical(INVENTORY.dotted(value), aliases_by_file[file])
            return value.attr in {'query', 'cursor'} or name.endswith('db.session')
        if isinstance(value, ast.Call):
            name = canonical(INVENTORY.dotted(value.func), aliases_by_file[file])
            return (name in {'sqlite3.connect', 'get_db'} or name.endswith('.cursor')
                    or resolve(file, INVENTORY.dotted(value.func), context) in tainted)
        return False

    changed = True
    while changed:
        changed = False
        for key, function in definitions.items():
            if key in tainted:
                continue
            file, context = key
            variables = set()
            nodes = list(own_nodes(function))
            growing = True
            while growing:
                before = len(variables)
                for node in nodes:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)) and is_object(node.value, file, variables, context):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        variables.update(target.id for target in targets if isinstance(target, ast.Name))
                growing = len(variables) > before
            if any(isinstance(node, ast.Return) and is_object(node.value, file, variables, context) for node in nodes):
                tainted.add(key)
                changed = True
    for file, tree in trees.items():
        if layers[file] not in HTTP_LAYERS:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and resolve(file, INVENTORY.dotted(node.func)) in tainted:
                emit(file, node.lineno, 'db_access_via_helper')


def resource_stems(endpoints):
    """Escolhe o primeiro segmento estático que não seja prefixo de API/versão."""
    resources = set()
    for endpoint in endpoints:
        for part in endpoint['path'].split('/'):
            if (not part or part.lower() == 'api' or re.fullmatch(r'v\d+(?:\.\d+)*', part, re.I)
                    or any(symbol in part for symbol in '<>:{}*')):
                continue
            resources.add(part.lower().removesuffix('s'))
            break
    return resources


def python_warnings(file, tree, layer, lines, warning_keys):
    """Avisos de adaptadores triviais e handlers grandes no ponto de entrada."""
    functions = [node for node in ast.walk(tree) if isinstance(node, FUNCTIONS)]
    if layer == 'controllers' and functions:
        delegates = []
        for node in functions:
            body = list(node.body)
            if ast.get_docstring(node) is not None:
                body = body[1:]
            delegates.append(len(body) == 1 and isinstance(body[0], ast.Return)
                             and isinstance(body[0].value, ast.Call))
        if all(delegates):
            warning_keys.add((file, 1, 'pass_through_controller', 0))
    if layer == 'entry':
        for node in functions:
            if any(python_route(dec) for dec in node.decorator_list) and body_size(node, lines) > 8:
                warning_keys.add((file, node.lineno, 'entry_has_handlers', 0))


def js_structure(text):
    """Tokeniza JavaScript e delimita funções sem interpretar strings/comentários."""
    tokens = INVENTORY.js_tokens(text)
    values = [token[0] if not token[2] else '__literal__' for token in tokens]
    pairs, stack = {}, []
    for i, value in enumerate(values):
        if value in {'(', '[', '{'}:
            stack.append(i)
        elif value in {')', ']', '}'} and stack:
            start = stack[-1]
            if {'(': ')', '[': ']', '{': '}'}[values[start]] == value:
                stack.pop()
                pairs[start], pairs[i] = i, start
    functions, seen = [], set()

    def add(start, body, name, arrow=False):
        if body >= len(values) or body in seen:
            return
        seen.add(body)
        block = values[body] == '{'
        if block:
            end = pairs.get(body)
            if end is None:
                return
        else:
            end = body
            while end < len(values) and values[end] not in {';', ',', ')', '}'}:
                end = pairs.get(end, end) + 1
        functions.append({'start': start, 'body': body, 'end': end, 'name': name,
                          'block': block, 'arrow': arrow})

    for i, value in enumerate(values):
        if value == '(' and i in pairs:
            close = pairs[i]
            after = close + 1
            if values[after:after + 2] == ['=', '>']:
                name = values[i - 2] if i >= 2 and values[i - 1] == '=' else ''
                add(i, after + 2, name, True)
            elif values[after:after + 1] == ['{']:
                previous = values[i - 1] if i else ''
                if previous == 'function':
                    add(i - 1, after, '')
                elif i >= 2 and values[i - 2] == 'function':
                    add(i - 2, after, previous)
                elif (re.fullmatch(r'[A-Za-z_$][\w$]*', previous)
                      and previous not in {'if', 'for', 'while', 'switch', 'catch', 'with'}):
                    add(i - 1, after, previous)
        elif value == '=' and values[i + 1:i + 2] == ['>'] and i and values[i - 1] != ')':
            name = values[i - 3] if i >= 3 and values[i - 2] == '=' else ''
            add(i - 1, i + 2, name, True)
    masked = list(text)
    for match in INVENTORY.JS_TOKEN_RE.finditer(text):
        if match.group('string') or match.group().startswith(('//', '/*')):
            masked[match.start():match.end()] = ['\n' if char == '\n' else ' ' for char in match.group()]
    return tokens, values, pairs, functions, ''.join(masked)


def js_module(file, name, sources):
    """Resolve somente caminhos relativos que já pertençam à lista permitida."""
    if not isinstance(name, str) or not name.startswith('.'):
        return None
    base = os.path.normpath(str(Path(file).parent / name)).replace(os.sep, '/')
    return next((candidate for candidate in [base] + [base + suffix for suffix in
                ('.js', '.mjs', '.cjs', '.ts', '/index.js', '/index.ts')]
                 if candidate in sources), None)


def js_body_lines(function, tokens, text):
    """Conta linhas do corpo e não conta a assinatura nem a chave de fechamento."""
    start, end = function['body'], function['end']
    signature_line = text.count('\n', 0, tokens[start][1]) + 1
    result = set()
    for token in tokens[start + (1 if function['block'] else 0):end]:
        if token[0] in {'{', '}', ';'}:
            continue
        line = text.count('\n', 0, token[1]) + 1
        if line > signature_line:
            result.update(range(line, line + token[0].count('\n') + 1))
    return len(result)


def js_call_name(values, opening):
    """Recupera identificadores encadeados anteriores a um parêntese."""
    end = opening - 1
    if end < 0 or not re.fullmatch(r'[A-Za-z_$][\w$]*', values[end]):
        return ''
    start = end
    while start >= 2 and values[start - 1] == '.' and re.fullmatch(r'[A-Za-z_$][\w$]*', values[start - 2]):
        start -= 2
    return ''.join(values[start:end + 1])


def js_delegates(function, values, pairs):
    """Aceita somente uma chamada retornada, sem outras instruções no corpo."""
    start = function['body'] + (1 if function['block'] else 0)
    end = function['end']
    if function['block']:
        if values[start:start + 1] != ['return']:
            return False
        start += 1
    if values[start:start + 1] == ['await']:
        start += 1
    opening = next((i for i in range(start, end) if values[i] == '('), None)
    if opening is None or not js_call_name(values, opening):
        return False
    if values[start:opening] != re.split(r'(\.)', js_call_name(values, opening)):
        return False
    close = pairs.get(opening)
    return close is not None and values[close + 1:end] in ([], [';'])


def js_dispatch_maps(tokens, values, pairs):
    """Encontra tabelas de pelo menos três ações associadas a funções."""
    mappings = set()
    for i in range(2, len(values)):
        if values[i] != '{' or values[i - 1] != '=' or i not in pairs:
            continue
        keys, end, position = set(), pairs[i], i + 1
        while position < end:
            key = INVENTORY.js_string(tokens[position]) if tokens[position][2] else values[position]
            if values[position + 1:position + 2] != [':']:
                break
            value_start = position + 2
            stop = value_start
            while stop < end and values[stop] != ',':
                stop = pairs.get(stop, stop) + 1
            expression = values[value_start:stop]
            if (isinstance(key, str) and expression and not tokens[value_start][2]
                    and expression[0] not in {'true', 'false', 'null', 'undefined'}
                    and (re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', ''.join(expression))
                         or expression[0] == 'function' or ['=', '>'] == expression[:2]
                         or any(expression[j:j + 2] == ['=', '>'] for j in range(len(expression) - 1)))):
                keys.add(key)
            position = stop + 1
        if len(keys) >= 3:
            mappings.add(values[i - 2])
    return mappings


def analyze_javascript(file, text, layer, sources, emit, warning_keys):
    """Regras lexicais de MVC para CommonJS, ESM e callbacks Express."""
    tokens, values, pairs, functions, code = js_structure(text)

    def line(i):
        return text.count('\n', 0, tokens[i][1]) + 1

    imports = []
    for i, value in enumerate(values):
        if value == 'require' and values[i + 1:i + 2] == ['('] and i + 2 < len(tokens):
            imports.append((INVENTORY.js_string(tokens[i + 2]), line(i)))
        elif value == 'import':
            if i + 1 < len(tokens) and tokens[i + 1][2]:
                imports.append((INVENTORY.js_string(tokens[i + 1]), line(i)))
            else:
                end = next((j for j in range(i + 1, min(i + 80, len(values)))
                            if values[j] in {'from', ';'}), None)
                if end is not None and values[end] == 'from' and end + 1 < len(tokens):
                    imports.append((INVENTORY.js_string(tokens[end + 1]), line(i)))
    if layer == 'routes':
        for name, number in imports:
            target = js_module(file, name, sources)
            if name and (data_import(name, {}, {}) or (target and layer_of(target) in DOMAIN_LAYERS)):
                emit(file, number, 'routes_import_data')
    route_functions = {}
    for i in range(len(values) - 4):
        if (values[i] not in {'app', 'router'} or values[i + 1] != '.'
                or values[i + 2] not in VERBS | {'all'} or values[i + 3] != '('):
            continue
        if INVENTORY.js_string(tokens[i + 4]) is None:
            continue
        if layer in DOMAIN_LAYERS | {'validators', 'other'}:
            emit(file, line(i), 'route_outside_http_layer')
        end = pairs.get(i + 3, i + 3)
        for function in functions:
            if i + 3 < function['start'] < function['end'] < end:
                route_functions[function['body']] = line(i)
    for function in functions:
        number = route_functions.get(function['body'], line(function['start']))
        if (layer == 'routes' or function['body'] in route_functions) and js_body_lines(function, tokens, text) > 8:
            emit(file, number, 'route_handler_too_long')
            if layer == 'entry':
                warning_keys.add((file, number, 'entry_has_handlers', 0))
    if layer in HTTP_LAYERS:
        pattern = (r'\bdb\s*\.\s*(?:run|all|get|each|exec|prepare|serialize)\s*\('
                   r'|\b(?:knex|sequelize)\b|\.\s*query\s*\(|\bnew\s+sqlite3\b')
        for match in re.finditer(pattern, code):
            emit(file, text.count('\n', 0, match.start()) + 1, 'db_access_in_http_layer')
    if layer in DOMAIN_LAYERS:
        for match in re.finditer(r'\b(?:req|res)\s*\.', code):
            emit(file, text.count('\n', 0, match.start()) + 1, 'http_in_domain')
        for i in range(len(values) - 2):
            key = INVENTORY.js_string(tokens[i]) if tokens[i][2] else values[i]
            status_call = values[max(0, i - 2):i + 1] == ['.', 'status', '(']
            status_field = key in {'status', 'statusCode'} and values[i + 1] == ':'
            number_index = i + 1 if status_call else i + 2
            if not (status_call or status_field) or number_index + 1 >= len(values):
                continue
            number = values[number_index]
            terminator = values[number_index + 1]
            if (re.fullmatch(r'[1-5]\d{2}', number)
                    and (terminator == ')' if status_call else terminator in {',', '}'})):
                emit(file, line(i), 'status_in_domain', tokens[i][1] + 1)
    if layer in {'routes', 'controllers'}:
        mappings = js_dispatch_maps(tokens, values, pairs)
        for i in range(len(values) - 2):
            if values[i] in mappings and values[i + 1] == '[':
                emit(file, line(i), 'string_dispatch_controller')
            if (values[i] in {'dispatch', 'handle', 'execute'} and values[i + 1] == '('
                    and action_literal(INVENTORY.js_string(tokens[i + 2]))):
                emit(file, line(i), 'string_dispatch_controller')
    if layer == 'controllers' and functions and all(js_delegates(function, values, pairs) for function in functions):
        warning_keys.add((file, 1, 'pass_through_controller', 0))
    return tokens, values, pairs, functions, code


def javascript_helper_checks(parsed, sources, layers, emit):
    """Segue retornos persistentes e imports CommonJS/ESM sem avaliar JavaScript."""
    definitions, imports, exports = {}, {}, {}
    for file, (tokens, values, pairs, functions, _) in parsed.items():
        for function in functions:
            if function['name']:
                definitions[(file, function['name'])] = function
        for i, value in enumerate(values):
            if value == 'require' and values[i + 1:i + 2] == ['('] and i + 2 < len(tokens):
                target = js_module(file, INVENTORY.js_string(tokens[i + 2]), sources)
                if target and i >= 2 and values[i - 1] == '=':
                    if values[i - 2] == '}' and i - 2 in pairs:
                        position = pairs[i - 2] + 1
                        while position < i - 2:
                            original = values[position]
                            local = original
                            if values[position + 1:position + 2] == [':']:
                                local = values[position + 2]
                                position += 2
                            imports[(file, local)] = (target, original)
                            position += 1
                            if values[position:position + 1] == [',']:
                                position += 1
                    else:
                        imports[(file, values[i - 2])] = (target, '')
            if value == 'import':
                end = next((j for j in range(i + 1, min(i + 80, len(values)))
                            if values[j] in {'from', ';'}), None)
                if end is None or values[end] != 'from' or end + 1 >= len(tokens):
                    continue
                target = js_module(file, INVENTORY.js_string(tokens[end + 1]), sources)
                if not target:
                    continue
                if values[i + 1] == '{':
                    position = i + 2
                    while position < end and values[position] != '}':
                        original, local = values[position], values[position]
                        if values[position + 1:position + 2] == ['as']:
                            local = values[position + 2]
                            position += 2
                        imports[(file, local)] = (target, original)
                        position += 1
                        if values[position:position + 1] == [',']:
                            position += 1
                elif values[i + 1:i + 3] == ['*', 'as']:
                    imports[(file, values[i + 3])] = (target, '')
                else:
                    imports[(file, values[i + 1])] = (target, 'default')
            if values[i:i + 4] == ['module', '.', 'exports', '='] and i + 4 < len(values):
                exports[(file, 'default')] = (file, values[i + 4])
            elif values[i:i + 2] == ['export', 'default'] and i + 2 < len(values):
                position = i + 3 if values[i + 2] == 'function' else i + 2
                if position < len(values):
                    exports[(file, 'default')] = (file, values[position])
            elif values[i:i + 2] == ['exports', '.'] and values[i + 3:i + 4] == ['='] and i + 4 < len(values):
                if (file, values[i + 2]) not in definitions:
                    exports[(file, values[i + 2])] = (file, values[i + 4])

    def resolve(file, name):
        head, separator, tail = name.partition('.')
        if (file, head) in imports:
            file, symbol = imports[(file, head)]
            name = symbol + separator + tail if symbol else (tail or 'default')
            if symbol == 'default' and tail:
                name = tail
        key, seen = (file, name), set()
        while key not in seen and key not in definitions and key in exports:
            seen.add(key)
            key = exports[key]
        return key if key in definitions else None

    tainted = set()
    for _ in range(len(definitions) + 1):
        before = len(tainted)
        for key, function in definitions.items():
            if key in tainted:
                continue
            file, _ = key
            tokens, values, pairs, functions, _ = parsed[file]
            start = function['body'] + (1 if function['block'] else 0)
            end = function['end']
            variables = set()

            def expression_end(position):
                while position < end and values[position] not in {';', ',', ')', ']', '}'}:
                    position = max(position, pairs.get(position, position)) + 1
                return position

            def is_object(first, last):
                while first < last and values[first] == '(' and pairs.get(first) == last - 1:
                    first, last = first + 1, last - 1
                if first < last and values[first] == 'await':
                    first += 1
                expression = values[first:last]
                name = ''.join(expression)
                if not expression:
                    return False
                if len(expression) == 1:
                    return name in variables | {'connection', 'conn', 'cursor'}
                if '(' not in expression:
                    return name.endswith(('.query', '.cursor')) or name == 'db.session'
                if expression[:2] == ['new', 'sqlite3']:
                    return True
                opening = next((j for j in range(first, last) if values[j] == '('), None)
                if opening is None or pairs.get(opening) != last - 1:
                    return False
                call = js_call_name(values, opening)
                return (call == 'sqlite3.connect' or call.endswith('.cursor')
                        or resolve(file, call) in tainted)

            positions = []
            position = start
            while position < end:
                nested = next((child for child in functions
                               if child is not function and child['start'] == position), None)
                if nested:
                    position = nested['end'] + 1
                else:
                    positions.append(position)
                    position += 1
            for _ in range(len(positions) + 1):
                old = len(variables)
                for position in positions:
                    if values[position] == '=' and position > start:
                        if is_object(position + 1, expression_end(position + 1)):
                            variables.add(values[position - 1])
                if len(variables) == old:
                    break
            returned = (not function['block'] and is_object(start, end)) or any(
                values[position] == 'return' and is_object(position + 1, expression_end(position + 1))
                for position in positions)
            if returned:
                tainted.add(key)
        if len(tainted) == before:
            break
    for file, (tokens, values, _, _, _) in parsed.items():
        if layers[file] not in HTTP_LAYERS:
            continue
        for i, value in enumerate(values):
            if value == '(' and resolve(file, js_call_name(values, i)) in tainted:
                emit(file, sources[file].count('\n', 0, tokens[i][1]) + 1, 'db_access_via_helper')


def collect(root):
    """Produz registros determinísticos sem incluir trechos de código."""
    sources = project_sources(root)
    layers = {file: layer_of(file) for file in sources}
    findings, warning_keys = set(), set()

    def emit(file, line, rule, occurrence=0):
        findings.add((file, line, rule, occurrence))

    modules = {}
    trees = {}
    for file, text in sources.items():
        if Path(file).suffix.lower() != '.py':
            continue
        module = file[:-3].replace('/', '.').removesuffix('.__init__')
        modules[module] = file
        try:
            trees[file] = ast.parse(text, feature_version=(3, 9))
        except SyntaxError as error:
            emit(file, error.lineno or 1, 'syntax_error')
    # O inventário recebe apenas fontes filtradas; collect() também leria metadados/exclusões diferentes.
    endpoints = INVENTORY.python_routes(sources)[0] + INVENTORY.javascript_routes(sources)[0]
    known_routes = {(endpoint['file'], endpoint['line']) for endpoint in endpoints}
    for file, tree in trees.items():
        for function in ast.walk(tree):
            if not isinstance(function, FUNCTIONS):
                continue
            for decorator in function.decorator_list:
                if python_route(decorator) and (file, decorator.lineno) not in known_routes:
                    endpoints.append({'file': file, 'line': decorator.lineno,
                                      'method': decorator.func.attr.upper(),
                                      'path': INVENTORY.literal(decorator.args[0])})
    resources = resource_stems(endpoints)
    for file, tree in trees.items():
        lines = code_lines(sources[file], tree)
        analyze_python(file, tree, layers[file], lines, modules, layers, emit)
        python_warnings(file, tree, layers[file], lines, warning_keys)
        names = [node.name.lower() for node in ast.walk(tree)
                 if isinstance(node, FUNCTIONS + (ast.ClassDef,))]
        if (layers[file] in DOMAIN_LAYERS | {'controllers'} and len(lines) > 300
                and sum(any(stem in name for name in names) for stem in resources) >= 3):
            emit(file, 1, 'god_module')
    python_helper_checks(trees, modules, layers, emit)
    parsed = {}
    for file, text in sources.items():
        if Path(file).suffix.lower() == '.py':
            continue
        parsed[file] = analyze_javascript(file, text, layers[file], sources, emit, warning_keys)
        tokens, _, _, functions, code = parsed[file]
        names = [function['name'].lower() for function in functions if function['name']]
        names += [match.group(1).lower() for match in re.finditer(r'\bclass\s+([A-Za-z_$][\w$]*)', code)]
        lines = {text.count('\n', 0, token[1]) + 1 + offset for token in tokens
                 for offset in range(token[0].count('\n') + 1)}
        if (layers[file] in DOMAIN_LAYERS | {'controllers'} and len(lines) > 300
                and sum(any(stem in name for name in names) for stem in resources) >= 3):
            emit(file, 1, 'god_module')
    javascript_helper_checks(parsed, sources, layers, emit)
    if endpoints and 'controllers' not in layers.values():
        location = next((file for file in sources if layers[file] == 'entry'), None)
        location = location or next((file for file in sources if layers[file] == 'routes'), None)
        emit(location or endpoints[0]['file'], 1, 'no_controller_layer')

    def records(items):
        return [{'file': file, 'line': line, 'rule': rule}
                for file, line, rule, _ in sorted(items)]

    return {'mvc': 'failed' if findings else 'ok',
            'files': [{'path': file, 'layer': layers[file]} for file in sources],
            'violations': records(findings), 'warnings': records(warning_keys)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not args.project_root.is_dir():
        print('ERROR=invalid-project-root', file=sys.stderr)
        return 2
    try:
        data = collect(args.project_root.resolve())
    except (OSError, UnicodeError, ValueError):
        print('ERROR=unreadable-project-source', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for item in data['files']:
            print('LAYER {path} {layer}'.format(**item))
        for key, prefix in [('violations', 'MVC_VIOLATION'), ('warnings', 'MVC_WARNING')]:
            for item in data[key]:
                print('{} {}:{} {}'.format(prefix, item['file'], item['line'], item['rule']))
        print('MVC={} FILES={} VIOLATIONS={} WARNINGS={}'.format(
            data['mvc'], len(data['files']), len(data['violations']), len(data['warnings'])))
    return 1 if data['violations'] else 0


if __name__ == '__main__':
    sys.exit(main())
