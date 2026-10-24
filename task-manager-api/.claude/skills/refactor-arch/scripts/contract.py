#!/usr/bin/env python3
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import copy
import fnmatch
import hashlib
import http.client
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

MESSAGE_KEYS = set('error errors erro erros message messages mensagem mensagens msg detail details'.split())
SENSITIVE_KEY = re.compile(r'pass|senha|secret|token|key|hash|salt|card|cvv|auth|cookie|credential|private', re.I)
SKIP_DIRS = set('.git .venv venv env node_modules __pycache__ .agents .claude tests test __tests__ instance coverage dist build'.split())
CASE_KEYS = set('id method path query headers body raw_body expect_status expect_json expect_json_keys forbid_json_keys note'.split())
ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z')
CONVERTER = re.compile(r'<(?:(\w+):)?(\w+)>|:(\w+)')
KINDS = {'none', 'malformed', 'null', 'bool', 'num', 'str', 'object', 'list', 'list0'}
DIFF_KINDS = set('missing_case added_case status content_type json missing_key added_key type message value text candidate_5xx'.split())


class InputError(ValueError):
    """Distingue mensagens locais de exceções que podem conter segredos."""


def fail(message):
    """Interrompe entradas inválidas sem expor seus valores."""
    raise InputError(message)


def load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def load_lines(path):
    rows = [json.loads(line) for line in pathlib.Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        fail('JSONL rows must be objects')
    ids = [row.get('id') for row in rows]
    if any(not isinstance(i, str) or not ID_RE.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
        fail('Invalid or duplicate case id')
    return rows


def write_json(path, value, lines=False):
    if lines:
        text = ''.join(json.dumps(row, ensure_ascii=True, sort_keys=True) + '\n' for row in value)
    else:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + '\n'
    pathlib.Path(path).write_text(text, encoding='utf-8')


def kind(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, (int, float)):
        return 'num'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'list' if value else 'list0'
    return 'str'


def fields(value, path='', tokens=()):
    """Percorre campos e o primeiro elemento de cada lista."""
    if isinstance(value, dict):
        for key, child in value.items():
            name = path + '.' + key if path else key
            yield name, tokens + (key,), child
            yield from fields(child, name, tokens + (key,))
    elif isinstance(value, list) and value:
        name = path + '[]'
        yield name, tokens + (0,), value[0]
        yield from fields(value[0], name, tokens + (0,))


def request_info(case):
    body_kind = 'malformed' if 'raw_body' in case else kind(case['body']) if 'body' in case else 'none'
    return {'body': body_kind, 'fields': {name: kind(v) for name, _, v in fields(case.get('body'))},
            'query': {k: kind(v) for k, v in case.get('query', {}).items()}}


def validate_cases(rows):
    for row in rows:
        if set(row) - CASE_KEYS or not {'id', 'method', 'path'} <= set(row):
            fail('Unknown or missing case keys')
        if not isinstance(row['method'], str) or not re.fullmatch('[A-Z]+', row['method']):
            fail('Invalid request method')
        if (not isinstance(row['path'], str) or not row['path'].startswith('/')
                or row['path'].startswith('//') or any(c in row['path'] for c in '?\r\n#')):
            fail('Invalid request path')
        if 'body' in row and 'raw_body' in row:
            fail('body and raw_body are mutually exclusive')
        if 'raw_body' in row and not isinstance(row['raw_body'], str):
            fail('raw_body must be a string')
        for key in ('query', 'headers'):
            if key in row and not isinstance(row[key], dict):
                fail('query and headers must be objects')
        if any(kind(v) not in {'str', 'num'} for v in row.get('query', {}).values()):
            fail('query values must be strings or numbers')
        if 'expect_status' in row and (
                not isinstance(row['expect_status'], list) or not row['expect_status']
                or any(type(n) is not int or not 100 <= n <= 599 for n in row['expect_status'])):
            fail('expect_status must contain HTTP statuses')
        for key in ('expect_json_keys', 'forbid_json_keys'):
            if key in row and (not isinstance(row[key], list) or not all(isinstance(v, str) for v in row[key])):
                fail('JSON key expectations must be string lists')
    return rows


def route_pattern(path, typed=True):
    parts, start = [], 0
    types = {'int': r'\d+', 'float': r'\d+\.\d+', 'uuid': r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', 'path': '.+'}
    for match in CONVERTER.finditer(path):
        parts.extend([re.escape(path[start:match.start()]), '(' + (types.get(match[1], '[^/]+') if typed else '[^/]+') + ')'])
        start = match.end()
    return '^' + ''.join(parts) + re.escape(path[start:]) + '$'


def load_routes(path):
    routes = []
    for line in pathlib.Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch('[A-Z]+', parts[0]) or not parts[1].startswith('/'):
            fail('Routes must contain METHOD /path')
        pair = tuple(parts)
        if pair in routes:
            fail('Duplicate route')
        routes.append(pair)
    if not routes:
        fail('Routes file is empty')
    return routes


def route_for(routes, method, path, typed=True):
    found = [r for r in routes if r[0] == method and re.fullmatch(route_pattern(r[1], typed), path)]
    return min(found, key=lambda r: len(list(CONVERTER.finditer(r[1])))) if found else None


def generated_id(seed):
    safe = re.sub(r'[^A-Za-z0-9._:-]', '-', seed.replace('[]', ':item'))
    return safe if len(safe) <= 64 else safe[:51] + '-' + hashlib.sha256(seed.encode()).hexdigest()[:12]


def scalar_variant(value):
    return 1 if isinstance(value, str) else True if type(value) in (int, float) else 'x'


def mutate_body(body, tokens, value=None, missing=False):
    result = copy.deepcopy(body)
    parent = result
    for token in tokens[:-1]:
        parent = parent[token]
    if missing:
        del parent[tokens[-1]]
    else:
        parent[tokens[-1]] = value
    return result


def scaffold(args):
    """Gera variantes observáveis sem presumir respostas de erro."""
    routes = load_routes(args.routes)
    cases = validate_cases(load_lines(args.success))
    selected = {}
    for case in cases:
        route = route_for(routes, case['method'], case['path'])
        if route is None or any(not 200 <= s < 300 for s in case.get('expect_status', [200])):
            fail('Success cases must match routes and expect only 2xx')
        selected.setdefault(route, case)
    if len(selected) != len(routes):
        fail('A success case is required for every route')
    variants = []

    def add(case, suffix, **changes):
        row = {k: copy.deepcopy(v) for k, v in case.items() if k in {'method', 'path', 'query', 'headers', 'body'}}
        row.update(changes)
        if 'raw_body' in row:
            row.pop('body', None)
        row['id'] = generated_id(case['id'] + '.' + suffix)
        variants.append(row)

    for route, case in selected.items():
        if 'body' in case:
            add(case, 'body.malformed', raw_body='{"')
            add(case, 'body.null', body=None)
            add(case, 'body.list', body={} if isinstance(case['body'], list) else ['x'])
            for name, tokens, value in fields(case['body']):
                alternatives = [('scalar', scalar_variant(value)),
                                ('list', {} if isinstance(value, list) else ['x']), ('null', None)]
                for label, replacement in alternatives:
                    add(case, 'wt.' + name + '.' + label, body=mutate_body(case['body'], tokens, replacement))
                if isinstance(tokens[-1], str):
                    add(case, 'wt.' + name + '.missing', body=mutate_body(case['body'], tokens, missing=True))
        for key, value in case.get('query', {}).items():
            if kind(value) == 'num':
                add(case, 'query.' + key, query=dict(case['query'], **{key: 'not-a-number'}))
        matches = list(CONVERTER.finditer(route[1]))
        actual = re.fullmatch(route_pattern(route[1]), case['path'])
        for index, match in enumerate(matches):
            if match[1] in {'int', 'float', 'uuid'}:
                start, end = actual.span(index + 1)
                add(case, 'typed.' + match[2], path=case['path'][:start] + 'not-a-' + match[1] + case['path'][end:])
    unknown = '/__contract_unknown__'
    while any(re.fullmatch(route_pattern(path, False), unknown) for _, path in routes):
        unknown += '/unknown'
        if len(unknown) > 1000:
            fail('Cannot generate an unknown URL for catch-all routes')
    variants.append({'id': 'coverage.unknown', 'method': 'GET', 'path': unknown})
    anchor = next(iter(selected.values()))
    method = next((m for m in ('PATCH', 'OPTIONS', 'TRACE', 'PROPFIND')
                   if route_for(routes, m, anchor['path'], False) is None), None)
    if method is None:
        fail('Cannot generate an unregistered method')
    variants.append({'id': 'coverage.method', 'method': method, 'path': anchor['path']})
    output = [c for c in cases if c['method'] != 'DELETE'] + variants + [c for c in cases if c['method'] == 'DELETE']
    if len({c['id'] for c in output}) != len(output):
        fail('Generated case id collision')
    validate_cases(output)
    write_json(args.out, output, True)
    if args.source:
        for message in extract_messages(args.source):
            print('MESSAGE {source} status={status}'.format(**message))
    print('SCAFFOLD=ok CASES={} SUCCESS={} GENERATED={}'.format(len(output), len(cases), len(variants)))
    return 0


def merge_shape(left, right):
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        return {k: merge_shape(left[k], right[k]) if k in left and k in right else left.get(k, right.get(k))
                for k in sorted(set(left) | set(right))}
    if isinstance(left, list) and isinstance(right, list):
        return [merge_shape(left[0], right[0])] if left and right else left or right
    return 'mixed'


def shape(value):
    if isinstance(value, dict):
        return {key: shape(child) for key, child in value.items()}
    if isinstance(value, list):
        merged = None
        for child in value:
            merged = shape(child) if merged is None else merge_shape(merged, shape(child))
        return [] if merged is None else [merged]
    return kind(value)


def mask_message(text):
    return re.sub(r'\d{12,}', '<masked>', text)[:200]


def message_text(value):
    if isinstance(value, str):
        return mask_message(value)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return mask_message('\n'.join(value))
    return None


def fingerprint(value):
    """Produz assinaturas sem registrar strings literais."""
    if isinstance(value, str):
        form = ''.join('9' if c.isdigit() else 'a' if c.isalpha() else c for c in value)
        return 's:' + hashlib.sha256(value.encode()).hexdigest()[:12] + ':' + form
    if isinstance(value, list):
        return 'len:' + str(len(value))
    if value is None:
        return 'null'
    return ('b:' if isinstance(value, bool) else 'n:') + json.dumps(value, separators=(',', ':'))


def response_maps(value):
    values, messages = {}, {}

    def walk(item, path):
        if not isinstance(item, dict) and len(values) < 1000:
            values[path] = fingerprint(item)
        if isinstance(item, dict):
            for key, child in item.items():
                if SENSITIVE_KEY.search(key):
                    continue
                child_path = path + '.' + key
                text = message_text(child)
                if key.lower() in MESSAGE_KEYS and text is not None:
                    messages[child_path] = text
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, path + '[' + str(index) + ']')
    walk(value, '$')
    return messages, values


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) >= len(expected)
                and all(subset(v, actual[i]) for i, v in enumerate(expected)))
    return kind(expected) == kind(actual) and expected == actual


def has_forbidden(value, keys):
    if isinstance(value, dict):
        return any(k in keys or has_forbidden(v, keys) for k, v in value.items())
    return isinstance(value, list) and any(has_forbidden(v, keys) for v in value)


def expectations(case, status, is_json, payload):
    errors = []
    if case.get('expect_status') and status not in case['expect_status']:
        errors.append('status')
    if 'expect_json_keys' in case and (not is_json or not isinstance(payload, dict)
                                       or any(k not in payload for k in case['expect_json_keys'])):
        errors.append('missing key')
    if is_json and has_forbidden(payload, set(case.get('forbid_json_keys', []))):
        errors.append('forbidden key')
    if 'expect_json' in case and (not is_json or not subset(case['expect_json'], payload)):
        errors.append('json subset')
    return errors


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def replay(args):
    """Executa cada caso uma vez e mantém apenas metadados seguros."""
    cases = validate_cases(load_lines(args.cases))
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        fail('Invalid base-url port')
    if (parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username
            or parsed.password or parsed.query or parsed.fragment or args.timeout <= 0):
        fail('base-url must be HTTP(S) without credentials, query or fragment; timeout must be positive')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    if args.update_defer and not args.defer:
        fail('--update-defer requires --defer')
    # Casos que derrubam o servidor original vão para o fim, na ordem relativa original, para que os demais
    # rodem no mesmo estado no baseline e no candidato.
    deferred = []
    if args.defer and pathlib.Path(args.defer).exists():
        deferred = load_json(args.defer)
        if not string_list(deferred) or len(set(deferred)) != len(deferred):
            fail('defer must be a list of unique case ids')
        if set(deferred) - {c['id'] for c in cases}:
            fail('defer contains unknown case ids')
    cases = [c for c in cases if c['id'] not in deferred] + [c for c in cases if c['id'] in deferred]
    rows, failed, tolerated, first_crash = [], 0, 0, None
    for index, case in enumerate(cases):
        is_deferred = case['id'] in deferred
        url = args.base_url.rstrip('/') + case['path']
        if case.get('query'):
            url += '?' + urllib.parse.urlencode(case['query'])
        headers = dict(case.get('headers', {}))
        data = None
        if 'body' in case or 'raw_body' in case:
            data = (case['raw_body'] if 'raw_body' in case else json.dumps(case['body'], ensure_ascii=False)).encode('utf-8')
            headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=data, headers=headers, method=case['method'])
        status, content_type, raw, disconnected = 0, '', b'', False
        try:
            try:
                response = opener.open(request, timeout=args.timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.code
                content_type = response.headers.get_content_type().lower()
                raw = response.read()
        except (OSError, urllib.error.URLError, TimeoutError, http.client.HTTPException):
            status, disconnected = 0, True
        text = raw.decode('utf-8', errors='replace')
        try:
            payload = json.loads(text)
            is_json = True
        except ValueError:
            payload, is_json = None, False
        messages, values = response_maps(payload) if is_json else ({}, {})
        errors = expectations(case, status, is_json, payload)
        if disconnected:
            errors.append('connection')
            print('DISCONNECTED id=' + case['id'])
            if not is_deferred and first_crash is None:
                first_crash = case['id']
        row = dict(id=case['id'], index=index, method=case['method'], path=case['path'], status=status,
                   content_type=content_type, json=is_json, shape=shape(payload) if is_json else None,
                   messages=messages, values=values, text_sha=None if is_json else hashlib.sha256(raw).hexdigest()[:16],
                   request=request_info(case), failures=errors, deferred=is_deferred)
        if not is_json:
            row['text_head'] = re.sub(r'\d', '9', text[:120])
        rows.append(row)
        # Queda de conexão em caso adiado e sem expectativa própria é o comportamento registrado do original.
        if is_deferred and errors == ['connection']:
            tolerated += 1
        else:
            failed += bool(errors)
        print('{:03d} {} {}'.format(status, case['method'], case['path']))
    write_json(args.record, rows, True)
    if args.update_defer:
        if first_crash is not None:
            write_json(args.defer, deferred + [first_crash])
            print('DEFER_UPDATED=yes id=' + first_crash)
        else:
            print('DEFER_UPDATED=no')
    if deferred:
        print('DEFERRED_DISCONNECTS={}'.format(tolerated))
    print('RESULT={} REQUESTS={} FAILED={}'.format('failed' if failed else 'ok', len(rows), failed))
    return int(bool(failed))


def python_messages(text):
    """Reconhece mensagens literais por AST, sem executar o projeto."""
    tree = ast.parse(text)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def scope(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return node
        return tree

    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault((scope(node), target.id), []).append((node.lineno, node.value))

    def resolve(node, seen=None):
        seen = set() if seen is None else seen
        if isinstance(node, ast.Name) and node.id not in seen:
            options = bindings.get((scope(node), node.id), []) + bindings.get((tree, node.id), [])
            options = [(line, value) for line, value in options if line < node.lineno]
            if options:
                return resolve(max(options, key=lambda pair: pair[0])[1], seen | {node.id})
        return node

    def literal(node):
        try:
            return ast.literal_eval(resolve(node))
        except (ValueError, TypeError, SyntaxError):
            return None

    def payload_messages(node):
        node = resolve(node)
        pairs = []
        if isinstance(node, (ast.List, ast.Tuple)):
            for child in node.elts:
                yield from payload_messages(child)
        if isinstance(node, ast.Dict):
            pairs = [(literal(k), v) for k, v in zip(node.keys, node.values) if k is not None]
        elif isinstance(node, ast.Call) and call_name(node) in {'jsonify', 'dict'}:
            for child in node.args:
                yield from payload_messages(child)
            pairs = [(kw.arg, kw.value) for kw in node.keywords]
        for key, value in pairs:
            if isinstance(key, str) and not SENSITIVE_KEY.search(key):
                msg = message_text(literal(value))
                if key.lower() in MESSAGE_KEYS and msg is not None:
                    yield msg
                yield from payload_messages(value)

    for node in ast.walk(tree):
        payload, status = None, None
        if isinstance(node, ast.Tuple) and len(node.elts) >= 2:
            payload, status = node.elts[0], literal(node.elts[1])
        elif isinstance(node, ast.Call) and call_name(node) in {'make_response', 'abort'} and node.args:
            if call_name(node) == 'abort':
                status = literal(node.args[0])
                payload = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == 'description'), None)
                msg = message_text(literal(payload)) if payload is not None else None
                if type(status) is int and 400 <= status < 500 and msg is not None:
                    yield node.lineno, status, msg
                continue
            if len(node.args) >= 2:
                payload, status = node.args[0], literal(node.args[1])
        if type(status) is int and 400 <= status < 500:
            for msg in payload_messages(payload):
                yield node.lineno, status, msg


def call_name(node):
    return node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''


JS_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|\d+|[^\s]')


def js_string(token):
    if not token or token[0] not in '\'"`':
        return None
    if token[0] == '`':
        return None if '${' in token else token[1:-1].replace('\\`', '`')
    try:
        return ast.literal_eval(token)
    except (ValueError, SyntaxError):
        return None


def js_messages(text):
    """Combina tokens e balanceamento de chaves para respostas Express."""
    tokens = [(m.group(), m.start()) for m in JS_TOKEN.finditer(text) if not m.group().startswith(('//', '/*'))]
    for index in range(len(tokens) - 10):
        seq = [t[0] for t in tokens[index:index + 11]]
        if not (seq[0] == 'res' and seq[1:4] == ['.', 'status', '(']
                and re.fullmatch('4[0-9]{2}', seq[4]) and seq[5:7] == [')', '.']
                and seq[7] in {'json', 'send'} and seq[8:10] == ['(', '{']):
            continue
        depth, end = 0, index + 9
        for end in range(index + 9, len(tokens)):
            token = tokens[end][0]
            depth += token == '{'
            depth -= token == '}'
            if depth == 0:
                break
        for pos in range(index + 10, end - 1):
            key = js_string(tokens[pos][0]) or tokens[pos][0]
            if key.lower() not in MESSAGE_KEYS or tokens[pos + 1][0] != ':':
                continue
            start, cursor = pos + 2, pos + 3
            value = js_string(tokens[start][0])
            if tokens[start][0] == '[':
                parts, cursor = [], start + 1
                while cursor < end and tokens[cursor][0] != ']':
                    part = js_string(tokens[cursor][0])
                    if part is None:
                        break
                    parts.append(part)
                    cursor += 1
                    if tokens[cursor][0] == ',':
                        cursor += 1
                value = parts if cursor < end and tokens[cursor][0] == ']' else None
                cursor += 1
            if cursor < len(tokens) and tokens[cursor][0] not in {',', '}'}:
                continue
            msg = message_text(value)
            if msg is not None:
                yield text.count('\n', 0, tokens[index][1]) + 1, int(seq[4]), msg


def extract_messages(source):
    source = pathlib.Path(source)
    if not source.is_dir():
        fail('source must be an existing directory')
    output = []
    paths = []
    for directory, directories, filenames in os.walk(source, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in SKIP_DIRS and not (pathlib.Path(directory) / d).is_symlink())
        paths.extend(pathlib.Path(directory) / name for name in sorted(filenames))
    for path in sorted(paths):
        relative = path.relative_to(source)
        if path.is_symlink() or not path.is_file():
            continue
        if path.name.startswith('test_') or path.name.endswith(('.test.js', '.spec.js')) or path.suffix not in {'.py', '.js'}:
            continue
        text = path.read_text(encoding='utf-8')
        try:
            found = python_messages(text) if path.suffix == '.py' else js_messages(text)
            for line, status, msg in found:
                entry = {'source': relative.as_posix() + ':' + str(line), 'status': status, 'text': msg}
                if entry not in output:
                    output.append(entry)
        except SyntaxError:
            fail('Cannot parse Python source')
    return sorted(output, key=lambda item: (item['source'], item['status'], item['text']))


def field_parent_present(info, name):
    if name.endswith('[]'):
        return False
    parent = name.rsplit('.', 1)[0] if '.' in name else ''
    return info['fields'].get(parent) == 'object' if parent else info['body'] == 'object'


def coverage(args):
    """Exige cada categoria sobre a forma do primeiro sucesso da rota."""
    routes = load_routes(args.routes)
    records = [r for r in load_lines(args.record) if r['status'] > 0 or r.get('deferred') is True]
    messages = extract_messages(args.source)
    declarations = load_json(args.unreachable) if args.unreachable else []
    if not isinstance(declarations, list):
        fail('unreachable must be a list')
    declared = set()
    for entry in declarations:
        if (not isinstance(entry, dict) or set(entry) != {'source', 'reason'}
                or not isinstance(entry['reason'], str) or not entry['reason'].strip()):
            fail('unreachable entries require source and non-empty reason')
        matched = [m for m in messages if m['source'] == entry['source']]
        if not matched:
            fail('unreachable source must point to an extracted message')
        for msg in matched:
            declared.add(msg['source'])
            print('DECLARED message {source} status={status}'.format(**msg))
    totals, gaps = {}, []

    def check(category, passed, label):
        hits, needed = totals.get(category, (0, 0))
        totals[category] = hits + bool(passed), needed + 1
        if not passed:
            gaps.append('MISSING ' + category + ' ' + label)

    body_count = 0
    for route in routes:
        label = ' '.join(route)
        group = [r for r in records if route_for(routes, r['method'], r['path']) == route]
        check('ROUTE', bool(group), label)
        success = next((r for r in group if 200 <= r['status'] < 300), None)
        check('SUCCESS', success is not None, label)
        if success is None:
            continue
        valid = success['request']
        infos = [r['request'] for r in group]
        if valid['body'] not in {'none', 'malformed'}:
            body_count += 1
            body_targets = [('MALFORMED', 'malformed'), ('NULL_BODY', 'null'),
                            ('LIST_BODY', 'object' if valid['body'] in {'list', 'list0'} else 'list')]
            for cat, target in body_targets:
                check(cat, any(i['body'] == target for i in infos), label)
            for name, expected in valid['fields'].items():
                variants = [('scalar', {'str', 'num', 'bool'} - {expected}),
                            ('list', {'object' if expected in {'list', 'list0'} else 'list'}), ('null', {'null'})]
                for variant, targets in variants:
                    passed = any(i['body'] == valid['body'] and i['fields'].get(name) in targets for i in infos)
                    check('WRONG_TYPE', passed, label + ' field=' + name + ' kind=' + variant)
                if not name.endswith('[]'):
                    absent = any(name not in i['fields'] and field_parent_present(i, name) for i in infos)
                    check('MISSING_FIELD', absent, label + ' field=' + name)
        for name, expected in valid['query'].items():
            if expected == 'num':
                check('QUERY_TYPE', any(i['query'].get(name) == 'str' for i in infos), label + ' query=' + name)
    for route in routes:
        label = ' '.join(route)
        converters = list(CONVERTER.finditer(route[1]))
        for index, converter in enumerate(converters):
            if converter[1] not in {'int', 'float', 'uuid'}:
                continue
            passed = False
            for row in records:
                match = re.fullmatch(route_pattern(route[1], False), row['path']) if row['method'] == route[0] else None
                if match:
                    value = match[index + 1]
                    pattern = route_pattern('<' + converter[1] + ':value>')
                    passed |= re.fullmatch(pattern, value) is None
            check('TYPED_PARAMS', passed, label + ' param=' + converter[2])
    unknown = sum(not any(re.fullmatch(route_pattern(path, False), r['path']) for _, path in routes) for r in records)
    wrong = sum(any(re.fullmatch(route_pattern(path), r['path']) for _, path in routes)
                and route_for(routes, r['method'], r['path']) is None for r in records)
    check('UNKNOWN_URL', unknown > 0, 'request')
    check('WRONG_METHOD', wrong > 0, 'request')
    seen = {mask_message(text) for r in records if 400 <= r['status'] < 500 for text in r.get('messages', {}).values()}
    for msg in messages:
        check('MESSAGES', msg['text'] in seen or msg['source'] in declared, msg['source'] + ' status=' + str(msg['status']))
    for gap in gaps:
        print(gap)
    categories = 'ROUTE SUCCESS MALFORMED NULL_BODY LIST_BODY WRONG_TYPE MISSING_FIELD QUERY_TYPE TYPED_PARAMS MESSAGES'.split()
    parts = {key: '{}/{}'.format(*totals.get(key, (0, 0))) for key in categories}
    summary = ('COVERAGE={result} ROUTES={ROUTE} SUCCESS={SUCCESS} BODY_ROUTES={body} '
               'MALFORMED={MALFORMED} NULL_BODY={NULL_BODY} LIST_BODY={LIST_BODY} '
               'WRONG_TYPE={WRONG_TYPE} MISSING_FIELD={MISSING_FIELD} QUERY_TYPE={QUERY_TYPE} '
               'UNKNOWN_URL={unknown} WRONG_METHOD={wrong} TYPED_PARAMS={TYPED_PARAMS} '
               'MESSAGES={MESSAGES} DECLARED={declared} GAPS={gaps}')
    print(summary.format(result='failed' if gaps else 'ok', body=body_count, unknown=unknown,
                         wrong=wrong, declared=len(declared), gaps=len(gaps), **parts))
    return int(bool(gaps))


def string_list(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_rules(rules):
    if not isinstance(rules, list):
        fail('Allow rules must be a list')
    for rule in rules:
        if (not isinstance(rule, dict)
                or set(rule) - {'id', 'route', 'kind', 'path', 'from', 'to', 'reason'}
                or rule.get('kind') not in DIFF_KINDS):
            fail('Unknown allow rule keys or kind')
        if not any(k in rule for k in ('id', 'route')) or not isinstance(rule.get('reason'), str) or not rule['reason'].strip():
            fail('Allow rules require a selector and non-empty reason')
        if any(not isinstance(rule[k], str) for k in ('id', 'route', 'path') if k in rule):
            fail('Allow rule selectors must be strings')
        if any(k in rule for k in ('from', 'to')) and rule['kind'] != 'status':
            fail('from/to are only valid for status rules')
        if any(type(rule[k]) is not int for k in ('from', 'to') if k in rule):
            fail('Status rule from/to must be integers')
    return rules


def crashed(record):
    """Caso adiado em que o servidor original derrubou a conexão (status 0)."""
    return record['status'] == 0 and record.get('deferred') is True and 'connection' in record.get('failures', [])


def matches_plan(case, record, match):
    for key, value in match.items():
        if key == 'id' and not fnmatch.fnmatchcase(case['id'], value):
            return False
        if key == 'route' and not fnmatch.fnmatchcase(case['method'] + ' ' + case['path'], value):
            return False
        if key == 'baseline_status' and record['status'] not in (value if isinstance(value, list) else [value]):
            return False
        if key == 'json' and record['json'] != value:
            return False
        if key == 'body_kind' and record['request']['body'] != value:
            return False
    return True


def strip_keys(value, keys):
    if isinstance(value, dict):
        return {k: strip_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [strip_keys(v, keys) for v in value]
    return value


def validate_change(change):
    actions = {'forbid_keys', 'set_headers', 'expect_status', 'expect_json_keys', 'allow', 'add_cases'}
    if (not isinstance(change, dict) or set(change) - actions - {'reason', 'match', 'changes_success'}
            or not actions.intersection(change)):
        fail('Unknown change keys or missing actions')
    if not isinstance(change.get('reason'), str) or not change['reason'].strip():
        fail('Changes require a non-empty reason')
    match = change.get('match')
    if not isinstance(match, dict) or not match or set(match) - {'id', 'route', 'baseline_status', 'json', 'body_kind'}:
        fail('Unknown or empty match')
    if (any(not isinstance(match[k], str) for k in ('id', 'route') if k in match)
            or ('json' in match and type(match['json']) is not bool)
            or ('body_kind' in match and match['body_kind'] not in KINDS)):
        fail('Invalid match value')
    if 'baseline_status' in match:
        statuses = match['baseline_status'] if isinstance(match['baseline_status'], list) else [match['baseline_status']]
        if not statuses or any(type(s) is not int or not (100 <= s <= 599 or s == 0) for s in statuses):
            fail('Invalid baseline_status')
    if 'changes_success' in change and type(change['changes_success']) is not bool:
        fail('changes_success must be a boolean')
    for key in ('forbid_keys', 'expect_json_keys'):
        if key in change and not string_list(change[key]):
            fail('Key actions must be string lists')
    if 'set_headers' in change and (not isinstance(change['set_headers'], dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in change['set_headers'].items())):
        fail('set_headers must map strings to strings')
    if 'expect_status' in change:
        validate_cases([dict(id='check', method='GET', path='/', expect_status=change['expect_status'])])
    if 'allow' in change:
        if not isinstance(change['allow'], list):
            fail('allow must be a list')
        for rule in change['allow']:
            if not isinstance(rule, dict) or set(rule) - {'kind', 'path'}:
                fail('Extra allow actions accept only kind and path')
            validate_rules([dict(rule, id='check', reason=change['reason'])])
    if 'add_cases' in change:
        if not isinstance(change['add_cases'], list):
            fail('add_cases must be a list')
        validate_cases(change['add_cases'])
        if any(not isinstance(c.get('id'), str) or not c['id'].startswith('add-') for c in change['add_cases']):
            fail('Added case ids must start with add-')


def derive(args):
    """Deriva expectativas e permissões somente das mudanças aprovadas."""
    cases = validate_cases(load_lines(args.cases))
    records = {row['id']: row for row in load_lines(args.record)}
    if (set(records) != {c['id'] for c in cases}
            or any(type(r['status']) is not int or not (100 <= r['status'] <= 599 or crashed(r))
                   for r in records.values())):
        fail('Every baseline case needs one connected record')
    if any(records[c['id']]['method'] != c['method'] or records[c['id']]['path'] != c['path']
           or records[c['id']]['request'] != request_info(c) for c in cases):
        fail('Baseline record request does not match its case')
    plan = load_json(args.plan)
    if not isinstance(plan, dict) or set(plan) != {'changes'} or not isinstance(plan['changes'], list):
        fail('Plan must contain only changes')
    output = copy.deepcopy(cases)
    by_id = {row['id']: row for row in output}
    additions, rules, changed = {}, [], set()
    for row in output:
        row['expect_status'] = [records[row['id']]['status']]
    for change in plan['changes']:
        validate_change(change)
        matched = [c for c in cases if matches_plan(c, records[c['id']], change['match'])]
        if not matched:
            fail('Change matched no baseline cases')
        for case in matched:
            row, record = by_id[case['id']], records[case['id']]
            changed.add(case['id'])
            reason = change['reason']
            def allow(kind_name, **extra):
                rules.append(dict(id=case['id'], kind=kind_name, reason=reason, **extra))
            if 'forbid_keys' in change:
                keys = set(change['forbid_keys'])
                row['forbid_json_keys'] = sorted(set(row.get('forbid_json_keys', [])) | keys)
                if 'expect_json' in row:
                    row['expect_json'] = strip_keys(row['expect_json'], keys)
                if 'expect_json_keys' in row:
                    row['expect_json_keys'] = [k for k in row['expect_json_keys'] if k not in keys]
                for key in sorted(keys):
                    allow('missing_key', path='*.' + key)
            if 'set_headers' in change:
                row['headers'] = dict(row.get('headers', {}), **change['set_headers'])
            if 'expect_status' in change:
                if (200 <= record['status'] < 300 or 400 <= record['status'] < 500) and change.get('changes_success') is not True:
                    fail('Changing recorded 2xx/4xx status requires changes_success=true')
                row['expect_status'] = change['expect_status']
                for status in change['expect_status']:
                    allow('status', **{'from': record['status'], 'to': status})
            if 'expect_json_keys' in change:
                forbidden = set(row.get('forbid_json_keys', []))
                row['expect_json_keys'] = [key for key in change['expect_json_keys'] if key not in forbidden]
            for rule in change.get('allow', []):
                allow(rule['kind'], **{k: v for k, v in rule.items() if k != 'kind'})
            for added in change.get('add_cases', []):
                additions.setdefault(case['id'], []).append(copy.deepcopy(added))
                rules.append(dict(id=added['id'], kind='added_case', reason=reason))
    unresolved = sorted(c['id'] for c in cases if crashed(records[c['id']])
                        and by_id[c['id']]['expect_status'] == [0])
    if unresolved:
        fail('Crash cases need an approved expect_status change: ' + ','.join(unresolved))
    result = []
    for row in output:
        result.extend(additions.get(row['id'], []))
        result.append(row)
    if len({c['id'] for c in result}) != len(result) or any(not ID_RE.fullmatch(c['id']) for c in result):
        fail('Invalid or duplicate derived case id')
    validate_cases(result)
    validate_rules(rules)
    write_json(args.out_cases, result, True)
    write_json(args.out_allow, {'rules': rules})
    print('DERIVE=ok CASES={} CHANGED={} ADDED={} RULES={}'.format(
        len(result), len(changed), len(result) - len(cases), len(rules)))
    return 0


def shape_diffs(left, right, path='$'):
    """Compara árvores de tipos sem depender dos valores literais."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child_path = path + '.' + key
            if key not in right:
                yield 'missing_key', child_path
            elif key not in left:
                yield 'added_key', child_path
            else:
                yield from shape_diffs(left[key], right[key], child_path)
    elif isinstance(left, list) and isinstance(right, list):
        if left and right:
            yield from shape_diffs(left[0], right[0], path + '[]')
        elif bool(left) != bool(right):
            yield 'type', path
    elif left != right:
        yield 'type', path


def glob_match(value, pattern):
    """Trata [] como notação literal de listas nos caminhos JSON."""
    pattern = pattern.replace('[', '[[]')
    return fnmatch.fnmatchcase(value, pattern)


def matches_rule(rule, row, kind_name, path, before, after):
    route = row['method'] + ' ' + row['path']
    return (rule['kind'] == kind_name and
            ('id' not in rule or fnmatch.fnmatchcase(row['id'], rule['id'])) and
            ('route' not in rule or fnmatch.fnmatchcase(route, rule['route'])) and
            ('path' not in rule or glob_match(path or '', rule['path'])) and
            ('from' not in rule or rule['from'] == before) and
            ('to' not in rule or rule['to'] == after))


def safe_value(value, kind_name):
    if kind_name == 'value':
        if isinstance(value, str) and re.fullmatch(r'(?:s:[0-9a-f]{12}:[\s\S]*|n:-?[\d.eE+]+|b:true|b:false|null|len:\d+)', value):
            return json.dumps(value, ensure_ascii=True)
        return json.dumps(fingerprint(str(value)))
    if kind_name == 'status':
        return str(value)
    return json.dumps(fingerprint(str(value)))


def compare(args):
    """Relata regressões estáveis e exige permissão explícita por diferença."""
    baseline = {r['id']: r for r in load_lines(args.baseline)}
    rerun = {r['id']: r for r in load_lines(args.rerun)}
    candidate = {r['id']: r for r in load_lines(args.candidate)}
    if set(baseline) != set(rerun):
        fail('Rerun must contain exactly the baseline ids')
    raw_rules = load_json(args.allow)
    if isinstance(raw_rules, dict):
        if set(raw_rules) != {'rules'}:
            fail('Allow file must contain only rules')
        raw_rules = raw_rules['rules']
    rules = validate_rules(raw_rules)
    volatility = {ident: {p for p in set(row.get('values', {})) | set(rerun[ident].get('values', {}))
                          if row.get('values', {}).get(p) != rerun[ident].get('values', {}).get(p) and not SENSITIVE_KEY.search(p)}
                  for ident, row in baseline.items()}
    # Corpo não JSON que já difere entre as duas execuções do baseline é volátil (ex.: debugger HTML).
    volatile_text = {ident for ident, row in baseline.items()
                     if not row['json'] and not rerun[ident]['json']
                     and row.get('text_sha') != rerun[ident].get('text_sha')}
    used, diffs, approved = set(), 0, 0
    volatile_count = sum(map(len, volatility.values())) + len(volatile_text)

    def emit(row, kind_name, path=None, before=None, after=None):
        nonlocal diffs, approved
        matches = [i for i, rule in enumerate(rules) if matches_rule(rule, row, kind_name, path, before, after)]
        used.update(matches)
        diffs += 1
        approved += bool(matches)
        text = 'DIFF id={} {} {} kind={}'.format(row['id'], row['method'], row['path'], kind_name)
        if path is not None:
            text += ' path=' + path
        if before is not None or after is not None:
            text += ' baseline={} candidate={}'.format(safe_value(before, kind_name), safe_value(after, kind_name))
        text += ' APPROVED: ' + rules[matches[0]]['reason'].replace('\n', ' ').replace('\r', ' ') if matches else ' UNAPPROVED'
        print(text)

    for ident in list(baseline) + [i for i in candidate if i not in baseline]:
        left, right = baseline.get(ident), candidate.get(ident)
        if right is None:
            emit(left, 'missing_case')
            continue
        if 500 <= right['status'] <= 599:
            emit(right, 'candidate_5xx')
        if left is None:
            emit(right, 'added_case')
            continue
        if crashed(left):
            # O original não respondeu: só existe o status para comparar (a resposta nova vem do plano aprovado).
            emit(right, 'status', before=0, after=right['status'])
            continue
        base_values = left.get('values', {})
        volatile = volatility[ident]
        for attr in ('status', 'content_type', 'json'):
            if left[attr] != right[attr]:
                emit(right, attr, before=left[attr], after=right[attr])
        if left['json'] != right['json']:
            continue
        if not left['json']:
            if ident not in volatile_text and left.get('text_sha') != right.get('text_sha'):
                emit(right, 'text', before=left.get('text_sha'), after=right.get('text_sha'))
            continue
        structural = list(shape_diffs(left['shape'], right['shape']))
        for kind_name, path in structural:
            emit(right, kind_name, path)
        structural_paths = [p for _, p in structural]
        def blocked(path):
            canonical = re.sub(r'\[\d+\]', '[]', path)
            return any(canonical == p or canonical.startswith(p + '.') or canonical.startswith(p + '[') for p in structural_paths)
        for path in sorted(set(left.get('messages', {})) | set(right.get('messages', {}))):
            unstable = any(v == path or v.startswith(path + '[') for v in volatile)
            if not unstable and not blocked(path) and not SENSITIVE_KEY.search(path):
                before, after = left.get('messages', {}).get(path), right.get('messages', {}).get(path)
                if before != after:
                    emit(right, 'message', path, before, after)
        after_values = right.get('values', {})
        for path in sorted(set(base_values) & set(after_values)):
            if path in volatile or blocked(path) or SENSITIVE_KEY.search(path):
                continue
            if base_values[path] != after_values[path]:
                emit(right, 'value', path, base_values[path], after_values[path])
    unused = len(rules) - len(used)
    for index, rule in enumerate(rules):
        if index not in used:
            print('UNUSED_RULE index={} kind={} id={} route={}'.format(
                index, rule['kind'], rule.get('id', '*'), rule.get('route', '*')))
    unapproved = diffs - approved
    print(('COMPARE={} CASES={} PAIRED={} DIFFS={} APPROVED={} UNAPPROVED={} '
           'UNUSED_RULES={} VOLATILE={}').format(
               'failed' if unapproved else 'ok', len(set(baseline) | set(candidate)),
               len(set(baseline) & set(candidate)), diffs, approved, unapproved, unused, volatile_count))
    return int(bool(unapproved))


def parser():
    root = argparse.ArgumentParser(description='HTTP regression contracts')
    commands = root.add_subparsers(dest='command', required=True)
    command = commands.add_parser('scaffold')
    for name in ('routes', 'success', 'out'):
        command.add_argument('--' + name, required=True)
    command.add_argument('--source')
    command = commands.add_parser('replay')
    for name in ('base-url', 'cases', 'record'):
        command.add_argument('--' + name, required=True)
    command.add_argument('--timeout', type=float, default=10)
    command.add_argument('--defer', help='JSON list of case ids replayed last (cases that crash the original)')
    command.add_argument('--update-defer', action='store_true',
                         help='append the first disconnected non-deferred case id to --defer')
    command = commands.add_parser('coverage')
    for name in ('routes', 'record', 'source'):
        command.add_argument('--' + name, required=True, help='Required for complete coverage')
    command.add_argument('--unreachable')
    command = commands.add_parser('derive')
    for name in ('cases', 'record', 'plan', 'out-cases', 'out-allow'):
        command.add_argument('--' + name, required=True)
    command = commands.add_parser('compare')
    for name in ('baseline', 'rerun', 'candidate', 'allow'):
        command.add_argument('--' + name, required=True)
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        return globals()[args.command](args)
    except (ValueError, OSError, TypeError, KeyError, http.client.HTTPException) as exc:
        print('ERROR invalid input: ' + (str(exc) if isinstance(exc, InputError) else type(exc).__name__), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
