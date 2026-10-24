import sys
sys.dont_write_bytecode = True

import contextlib
import importlib.util
import json
import pathlib
import socket
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'contract.py'
SECRET = 'CANARY-SECRET-DO-NOT-PRINT-7b1c8'


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.do_GET()

    def do_PATCH(self):
        self.do_GET()

    def do_GET(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        type(self).seen.append((self.command, self.path, raw, self.headers.get('Content-Type')))
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/ok')
            self.end_headers()
            return
        if self.path == '/truncate':
            self.send_response(200)
            self.send_header('Content-Length', '100')
            self.end_headers()
            self.wfile.write(b'no')
            return
        if self.path == '/crash':
            # Simula um legado que cai: fecha a conexão sem responder.
            self.close_connection = True
            return
        if self.path == '/html':
            status, ctype, body = 502, 'text/html', b'<h1>failure 123</h1>'
        elif self.path == '/invalid':
            status, ctype, body = 400, 'application/json', b'{broken'
        else:
            status, ctype = 200, 'application/json; charset=utf-8'
            body = json.dumps({'ok': True, 'password': SECRET, 'nested': {'token': SECRET},
                               'message': 'account 123456789012 denied',
                               'errors': ['one', 'two'], 'values': [1, 'ab12'],
                               'nil': None, 'mixed': [{'a': 1}, {'b': True}]}).encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        self.wfile.write(body)


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def put(self, name, value, lines=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = ''.join(json.dumps(x) + '\n' for x in value) if lines else (
            value if isinstance(value, str) else json.dumps(value))
        path.write_text(text, encoding='utf-8')
        return path

    def run_cli(self, *args, code=0):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *map(str, args)],
                                text=True, capture_output=True, timeout=15)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def read_lines(self, name):
        return [json.loads(x) for x in (self.root / name).read_text().splitlines() if x]

    def scaffold(self, routes, cases):
        return self.run_cli('scaffold', '--routes', self.put('routes.txt', routes),
                            '--success', self.put('success.jsonl', cases, True),
                            '--out', self.root / 'cases.jsonl')

    def test_scaffold_nested_wrong_types_and_order(self):
        cases = [
            {'id': 'delete', 'method': 'DELETE', 'path': '/things/1', 'expect_status': [204]},
            {'id': 'post', 'method': 'POST', 'path': '/things', 'body': {
                'name': 'ok', 'count': 2, 'active': True, 'meta': {'a': 1},
                'items': [{'qty': 2}], 'tags': ['a']}, 'expect_status': [201]},
            {'id': 'get', 'method': 'GET', 'path': '/things/1', 'query': {'limit': 2},
             'expect_status': [200]},
            {'id': 'list', 'method': 'POST', 'path': '/batch', 'body': [{'qty': 1}],
             'expect_status': [200]},
        ]
        routes = 'DELETE /things/<int:id>\nPOST /things\nGET /things/<int:id>\nPOST /batch\n'
        self.assertIn('SCAFFOLD=ok', self.scaffold(routes, cases))
        generated = self.read_lines('cases.jsonl')
        self.assertEqual([x['id'] for x in generated[:3]], ['post', 'get', 'list'])
        self.assertEqual(generated[-1]['id'], 'delete')
        by_id = {x['id']: x for x in generated}
        self.assertEqual(len(by_id), len(generated))
        for field in ('name', 'count', 'active', 'meta', 'meta.a', 'items',
                      'items[]', 'items[].qty', 'tags', 'tags[]'):
            for variant in ('scalar', 'list', 'null'):
                self.assertIn('post.wt.' + field.replace('[]', ':item') + '.' + variant, by_id)
        self.assertEqual(by_id['post.wt.items.list']['body']['items'], {})
        self.assertEqual(by_id['post.wt.name.list']['body']['name'], ['x'])
        self.assertIsInstance(by_id['post.wt.count.scalar']['body']['count'], bool)
        self.assertEqual(by_id['post.wt.meta.a.missing']['body']['meta'], {})
        self.assertNotIn('post.wt.items[].missing', by_id)
        self.assertEqual(by_id['post.body.list']['body'], ['x'])
        self.assertEqual(by_id['list.body.list']['body'], {})
        self.assertIsNone(by_id['post.body.null']['body'])
        self.assertIn('raw_body', by_id['post.body.malformed'])
        self.assertEqual(by_id['get.query.limit']['query']['limit'], 'not-a-number')
        self.assertTrue(any('typed' in x['id'] for x in generated))
        self.assertTrue(any('unknown' in x['id'] for x in generated))
        self.assertTrue(any('method' in x['id'] for x in generated))
        first = (self.root / 'cases.jsonl').read_bytes()
        self.scaffold(routes, cases)
        self.assertEqual(first, (self.root / 'cases.jsonl').read_bytes())


    @contextlib.contextmanager
    def server(self):
        Handler.seen = []
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield 'http://127.0.0.1:' + str(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_replay_records_and_request_kinds(self):
        cases = [dict(id='none', method='GET', path='/ok', query={'limit': 2},
                      expect_status=[200], expect_json={'ok': True}, expect_json_keys=['nil']),
                 dict(id='null', method='POST', path='/ok', body=None),
                 dict(id='list', method='POST', path='/ok', body=[{'qty': 2}]),
                 dict(id='empty', method='POST', path='/ok', body=[]),
                 dict(id='raw', method='POST', path='/invalid', raw_body='{', expect_status=[400]),
                 dict(id='html', method='GET', path='/html', expect_status=[502])]
        with self.server() as url:
            stdout = self.run_cli('replay', '--base-url', url, '--cases', self.put('in.jsonl', cases, True),
                                  '--record', self.root / 'record.jsonl')
        self.assertIn('RESULT=ok REQUESTS=6 FAILED=0', stdout)
        records = self.read_lines('record.jsonl')
        self.assertEqual([r['request']['body'] for r in records], ['none', 'null', 'list', 'list0', 'malformed', 'none'])
        self.assertEqual(records[2]['request']['fields'], {'[]': 'object', '[].qty': 'num'})
        self.assertEqual([r['index'] for r in records], list(range(6)))
        first = records[0]
        self.assertEqual(first['content_type'], 'application/json')
        self.assertEqual(first['shape']['mixed'], [{'a': 'num', 'b': 'bool'}])
        self.assertEqual(first['values']['$.values'], 'len:2')
        self.assertEqual(first['values']['$.nil'], 'null')
        self.assertEqual(first['values']['$.ok'], 'b:true')
        self.assertRegex(first['values']['$.values[1]'], r'^s:[0-9a-f]{12}:aa99$')
        self.assertFalse(any('password' in k or 'token' in k for k in first['values']))
        self.assertEqual(first['messages']['$.message'], 'account <masked> denied')
        self.assertEqual(first['messages']['$.errors'], 'one\ntwo')
        self.assertFalse(records[-1]['json'])
        self.assertEqual(len(records[-1]['text_sha']), 16)
        self.assertEqual(records[-1]['text_head'], '<h9>failure 999</h9>')
        self.assertEqual(Handler.seen[1][2:], (b'null', 'application/json'))
        self.assertEqual(Handler.seen[4][2:], (b'{', 'application/json'))
        self.assertNotIn(SECRET, (self.root / 'record.jsonl').read_text())

    def test_replay_expectations_and_closed_port(self):
        cases = [dict(id='bad', method='GET', path='/ok', expect_status=[404],
                      expect_json={'ok': False}, expect_json_keys=['absent'],
                      forbid_json_keys=['token'])]
        with self.server() as url:
            self.run_cli('replay', '--base-url', url, '--cases', self.put('in.jsonl', cases, True),
                         '--record', self.root / 'r.jsonl', code=1)
        record = self.read_lines('r.jsonl')[0]
        self.assertEqual(set(record['failures']), {'status', 'missing key', 'forbidden key', 'json subset'})
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        stdout = self.run_cli('replay', '--base-url', 'http://127.0.0.1:' + str(port),
                              '--cases', self.put('in.jsonl', [dict(id='down', method='GET', path='/')], True),
                              '--record', self.root / 'down.jsonl', '--timeout', '0.2', code=1)
        self.assertIn('000 GET /', stdout)
        self.assertEqual(self.read_lines('down.jsonl')[0]['status'], 0)


    def test_replay_defer_moves_crash_cases_last_and_updates_file(self):
        cases = [dict(id='a', method='GET', path='/ok'), dict(id='crash', method='GET', path='/crash'),
                 dict(id='b', method='GET', path='/ok')]
        source = self.put('cases.jsonl', cases, True)
        defer = self.root / 'defer.json'
        with self.server() as url:
            stdout = self.run_cli('replay', '--base-url', url, '--cases', source, '--record', self.root / 'r1.jsonl',
                                  '--defer', defer, '--update-defer', '--timeout', '2', code=1)
            self.assertIn('DISCONNECTED id=crash', stdout)
            self.assertIn('DEFER_UPDATED=yes id=crash', stdout)
            self.assertEqual(json.loads(defer.read_text()), ['crash'])
            stdout = self.run_cli('replay', '--base-url', url, '--cases', source, '--record', self.root / 'r2.jsonl',
                                  '--defer', defer, '--update-defer', '--timeout', '2')
            self.assertIn('DEFER_UPDATED=no', stdout)
            self.assertIn('DEFERRED_DISCONNECTS=1', stdout)
            self.assertIn('RESULT=ok REQUESTS=3 FAILED=0', stdout)
            rows = self.read_lines('r2.jsonl')
            self.assertEqual([r['id'] for r in rows], ['a', 'b', 'crash'])
            self.assertEqual([r['deferred'] for r in rows], [False, False, True])
            self.assertEqual(rows[2]['status'], 0)
            # Um caso adiado com expectativa própria continua falhando se a conexão cair.
            strict = cases[:1] + [dict(cases[1], expect_status=[400])]
            self.run_cli('replay', '--base-url', url, '--cases', self.put('strict.jsonl', strict, True),
                         '--record', self.root / 'r3.jsonl', '--defer', defer, '--timeout', '2', code=1)
            self.put('unknown.json', ['missing-id'])
            self.run_cli('replay', '--base-url', url, '--cases', source, '--record', self.root / 'r4.jsonl',
                         '--defer', self.root / 'unknown.json', code=2)
            self.run_cli('replay', '--base-url', url, '--cases', source, '--record', self.root / 'r5.jsonl',
                         '--update-defer', code=2)

    def test_derive_crash_cases_require_approved_status(self):
        cases = [dict(id='ok', method='GET', path='/'), dict(id='crash', method='POST', path='/', body={'n': 1})]
        crash = self.record(cases[1], 0, content_type='', json=False, shape=None, text_sha='e3b0c44298fc1c14',
                            failures=['connection'], deferred=True)
        records = [self.record(cases[0]), crash]
        for match in ({'id': 'crash'}, {'baseline_status': 0}):
            with self.subTest(match=match):
                plan = {'changes': [dict(reason='C3 tipos inválidos', match=match, expect_status=[400])]}
                self.assertIn('DERIVE=ok', self.derive(cases, records, plan))
                result = {c['id']: c for c in self.read_lines('cand.jsonl')}
                self.assertEqual(result['crash']['expect_status'], [400])
                rules = json.loads((self.root / 'allow.json').read_text())['rules']
                self.assertIn({'id': 'crash', 'kind': 'status', 'reason': 'C3 tipos inválidos', 'from': 0, 'to': 400},
                              rules)
        self.derive(cases, records, {'changes': []}, code=2)
        not_deferred = dict(crash, deferred=False)
        plan = {'changes': [dict(reason='C3', match={'id': 'crash'}, expect_status=[400])]}
        self.derive(cases, [records[0], not_deferred], plan, code=2)

    def test_compare_crash_baseline_compares_only_status(self):
        case = dict(id='crash', method='POST', path='/', body={'n': 1})
        base = self.record(case, 0, content_type='', json=False, shape=None, text_sha='e3b0c44298fc1c14',
                           failures=['connection'], deferred=True)
        cand = self.record(case, 400, content_type='text/plain', json=False, shape=None, text_sha='aaaaaaaaaaaaaaaa')
        rule = {'id': 'crash', 'kind': 'status', 'from': 0, 'to': 400, 'reason': 'C3'}
        stdout = self.compare([base], [cand], [rule])
        self.assertIn('COMPARE=ok CASES=1 PAIRED=1 DIFFS=1 APPROVED=1 UNAPPROVED=0', stdout)
        self.assertIn('COMPARE=failed', self.compare([base], [cand], [], code=1))

    def test_coverage_counts_deferred_crash_records_only(self):
        success = dict(id='s', method='POST', path='/items', body={'name': 'a'})
        crash_case = dict(id='c', method='POST', path='/items', body={'name': 1})
        gap = 'MISSING WRONG_TYPE POST /items field=name kind=scalar'
        for deferred, present in ((True, False), (False, True)):
            with self.subTest(deferred=deferred):
                crash = self.record(crash_case, 0, failures=['connection'], deferred=deferred)
                stdout = self.coverage('POST /items\n', [self.record(success, 201), crash], code=1)
                self.assertEqual(gap in stdout, present, stdout)

    def module(self):
        spec = importlib.util.spec_from_file_location('contract_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def record(self, case, status=200, **extra):
        row = dict(id=case['id'], index=0, method=case['method'], path=case['path'], status=status,
                   content_type='application/json', json=True, shape={}, messages={}, values={},
                   text_sha=None, request=self.module().request_info(case), failures=[])
        row.update(extra)
        return row

    def coverage(self, routes, records, source=None, code=0, unreachable=None):
        if source is None:
            source = self.root / 'src'
            source.mkdir(exist_ok=True)
        args = ['coverage', '--routes', self.put('routes.txt', routes),
                '--record', self.put('baseline.jsonl', records, True), '--source', source]
        if unreachable is not None:
            args += ['--unreachable', self.put('unreachable.json', unreachable)]
        return self.run_cli(*args, code=code)

    def test_coverage_scaffold_pass_and_empty_list_gap(self):
        cases = [dict(id='post', method='POST', path='/things', body={'a': 1, 'nested': {'x': 's'}, 'tags': ['x']}, expect_status=[200]),
                 dict(id='get', method='GET', path='/things/1', query={'limit': 2}, expect_status=[200]),
                 dict(id='list', method='POST', path='/batch', body=[{'qty': 2}], expect_status=[200])]
        routes = 'POST /things\nGET /things/<int:id>\nPOST /batch\n'
        self.scaffold(routes, cases)
        records = [self.record(c) for c in self.read_lines('cases.jsonl')]
        stdout = self.coverage(routes, records)
        self.assertIn('COVERAGE=ok ROUTES=3/3 SUCCESS=3/3 BODY_ROUTES=2', stdout)
        self.assertIn('GAPS=0', stdout)
        for record in records:
            if record['id'] == 'post.body.list':
                record['request']['body'] = 'list0'
        stdout = self.coverage(routes, records, code=1)
        self.assertIn('MISSING LIST_BODY', stdout)
        self.assertIn('LIST_BODY=1/2', stdout)
        records = [r for r in records if r['id'] != 'post.wt.nested.x.missing']
        stdout = self.coverage(routes, records, code=1)
        self.assertIn('MISSING MISSING_FIELD POST /things field=nested.x', stdout)

    def test_coverage_reports_every_gap_and_requires_source(self):
        case = dict(id='post', method='POST', path='/x/1', body={'a': 1}, query={'n': 2})
        stdout = self.coverage('POST /x/<int:id>\nGET /other\n', [self.record(case)], code=1)
        for category in ('ROUTE', 'SUCCESS', 'MALFORMED', 'NULL_BODY', 'LIST_BODY', 'WRONG_TYPE',
                         'MISSING_FIELD', 'QUERY_TYPE', 'UNKNOWN_URL', 'WRONG_METHOD', 'TYPED_PARAMS'):
            self.assertIn('MISSING ' + category, stdout)
        self.run_cli('coverage', '--routes', self.root / 'routes.txt', '--record', self.root / 'baseline.jsonl', code=2)

    def message_sources(self):
        self.put('src/app.py', '''from flask import jsonify, make_response, abort

def one():
    payload = {"error": "tuple literal"}
    return payload, 400

def two():
    return make_response(jsonify(
        error="kwargs literal", messages=["many", "lines"]
    ), 422)

def three():
    abort(403, "abort positional")
    abort(401, description="abort keyword")
    return (dict(message="dict literal"), 409)

def four():
    return jsonify({"error": f"dynamic {42}"}), 400
    return {"error": "server failure"}, 500
    return {"message": "success"}, 200
''')
        self.put('src/routes.js', '''res.status(400).json({
    error: "js multiline", nested: { message: 'nested js' },
    errors: ["first", "second"], details: `static template`
});
res.status(422).send({ message: `dynamic ${value}` });
res.status(500).json({error: "server js"});
res.status(201).json({message: "created"});
''')
        for name in ('tests/no.py', 'node_modules/no.js', 'test_skip.py', 'route.test.js', 'route.spec.js', 'instance/no.py'):
            self.put('src/' + name, 'res.status(400).json({error:"ignored"});\n' if name.endswith('js') else 'x = ({"error":"ignored"},400)\n')
        return self.root / 'src'

    def test_message_extraction_flask_express_and_unreachable(self):
        source = self.message_sources()
        case = dict(id='ok', method='GET', path='/')
        record = self.record(case)
        stdout = self.coverage('GET /\n', [record], source, code=1)
        self.assertIn('MESSAGES=0/10', stdout)
        self.assertNotIn('tuple literal', stdout)
        self.assertNotIn('dynamic', stdout)
        messages = self.module().extract_messages(source)
        self.assertEqual(len(messages), 10)
        texts = {m['text'] for m in messages}
        self.assertIn('many\nlines', texts)
        self.assertNotIn('server failure', texts)
        self.assertNotIn('ignored', texts)
        records = [record, self.record(dict(id='unknown', method='GET', path='/unknown'), 404),
                   self.record(dict(id='method', method='PATCH', path='/'), 405)]
        for index, text in enumerate(sorted(texts)):
            records.append(self.record(dict(id='msg' + str(index), method='GET', path='/'), 400, messages={'$.error': text}))
        self.assertIn('COVERAGE=ok', self.coverage('GET /\n', records, source))
        declarations = [{'source': m['source'], 'reason': SECRET} for m in messages]
        stdout = self.coverage('GET /\n', records[:3], source, unreachable=declarations)
        self.assertIn('DECLARED message app.py:5 status=400', stdout)
        self.coverage('GET /\n', records, source, code=2, unreachable=[{'source': 'absent.py:1', 'reason': 'not possible'}])
        self.coverage('GET /\n', records, source, code=2, unreachable=[{'source': messages[0]['source'], 'reason': ''}])
        stdout = self.run_cli('scaffold', '--routes', self.root / 'routes.txt', '--success', self.put('success.jsonl', [case], True),
                              '--source', source, '--out', self.root / 'scaffold.jsonl')
        self.assertEqual(stdout.count('MESSAGE '), 10)


    def derive(self, cases, records, plan, code=0):
        return self.run_cli('derive', '--cases', self.put('base.cases.jsonl', cases, True),
                            '--record', self.put('base.record.jsonl', records, True),
                            '--plan', self.put('plan.json', plan), '--out-cases', self.root / 'cand.jsonl',
                            '--out-allow', self.root / 'allow.json', code=code)

    def test_derive_pins_preserves_requests_and_applies_actions(self):
        cases = [dict(id='ok', method='GET', path='/users/1', expect_status=[200, 201],
                      expect_json={'password': SECRET, 'items': [{'token': SECRET, 'name': 'a'}]},
                      expect_json_keys=['password', 'items']),
                 dict(id='err', method='POST', path='/users', body={'name': 'a'}, expect_status=[500]),
                 dict(id='tail', method='DELETE', path='/users/1')]
        records = [self.record(cases[0], 201), self.record(cases[1], 500), self.record(cases[2], 204)]
        changes = [dict(reason='remove sensitive fields', match={'route': 'GET /users/*', 'baseline_status': [201], 'json': True, 'body_kind': 'none'},
                        forbid_keys=['password', 'token'], set_headers={'X-Test': 'yes'}, expect_json_keys=['items'],
                        allow=[{'kind': 'content_type'}], add_cases=[dict(id='add-check', method='GET', path='/health', expect_status=[200])]),
                   dict(reason='validate errors', match={'id': 'err', 'baseline_status': 500}, expect_status=[400])]
        stdout = self.derive(cases, records, {'changes': changes})
        self.assertIn('DERIVE=ok CASES=4 CHANGED=2 ADDED=1', stdout)
        result = self.read_lines('cand.jsonl')
        self.assertEqual([c['id'] for c in result], ['add-check', 'ok', 'err', 'tail'])
        self.assertEqual(result[1]['expect_status'], [201])
        self.assertEqual(result[2]['expect_status'], [400])
        self.assertEqual(result[3]['expect_status'], [204])
        self.assertEqual(result[1]['expect_json'], {'items': [{'name': 'a'}]})
        self.assertEqual(result[1]['expect_json_keys'], ['items'])
        self.assertEqual(result[1]['headers'], {'X-Test': 'yes'})
        self.assertEqual(result[2]['body'], cases[1]['body'])
        rules = json.loads((self.root / 'allow.json').read_text())['rules']
        self.assertTrue(all(r['reason'] for r in rules))
        self.assertEqual({r['kind'] for r in rules}, {'missing_key', 'status', 'content_type', 'added_case'})

    def test_derive_refuses_unapproved_or_invalid_changes(self):
        case = dict(id='ok', method='GET', path='/')
        for status in (200, 400):
            with self.subTest(status=status):
                change = dict(reason='status', match={'id': 'ok'}, expect_status=[422])
                self.derive([case], [self.record(case, status)], {'changes': [change]}, code=2)
                change['changes_success'] = True
                self.derive([case], [self.record(case, status)], {'changes': [change]})
        invalid = [
            {'changes': [], 'unknown': True},
            {'changes': [dict(reason='x', match={'id': 'none'}, allow=[{'kind': 'value'}])]},
            {'changes': [dict(reason='x', match={'unknown': True}, allow=[{'kind': 'value'}])]},
            {'changes': [dict(reason='x', match={'id': '*'}, typo=True)]},
            {'changes': [dict(reason='', match={'id': '*'}, allow=[{'kind': 'value'}])]},
            {'changes': [dict(reason='x', match={'id': '*'}, allow=[{'kind': 'oops'}])]},
            {'changes': [dict(reason='x', match={'id': '*'}, allow=[{'kind': 'value', 'unknown': 1}])]},
            {'changes': [dict(reason='x', match={'id': '*'}, add_cases=[dict(id='not-add', method='GET', path='/')])]},
        ]
        for plan in invalid:
            with self.subTest(plan=plan):
                self.derive([case], [self.record(case)], plan, code=2)
        self.derive([case], [], {'changes': []}, code=2)
        self.derive([case], [self.record(case, 0)], {'changes': []}, code=2)


    def compare(self, baseline, candidate, rules=None, rerun=None, code=0):
        return self.run_cli('compare', '--baseline', self.put('b.jsonl', baseline, True),
                            '--rerun', self.put('b2.jsonl', baseline if rerun is None else rerun, True),
                            '--candidate', self.put('c.jsonl', candidate, True),
                            '--allow', self.put('rules.json', {'rules': rules or []}), code=code)

    def test_compare_all_diff_kinds_without_secret_output(self):
        baseline, candidate = [], []
        variants = {
            'status': {'status': 201}, 'content_type': {'content_type': 'text/custom'},
            'json': {'json': False}, 'missing_key': {'shape': {}},
            'added_key': {'shape': {'x': 'str', 'y': 'num'}}, 'type': {'shape': {'x': 'bool'}},
            'message': {'messages': {'$.message': SECRET}},
            'value': {'values': {'$.x': 's:012345678abc:aaaa'}},
            'text': {'json': False, 'text_sha': 'new'}, 'candidate_5xx': {'status': 503},
        }
        for name, changes in variants.items():
            before = self.record(dict(id=name, method='GET', path='/users/1'), shape={'x': 'str'},
                                 values={'$.x': 's:abcdef012345:aaaa'})
            if name == 'text':
                before.update(json=False, text_sha='old')
            if name == 'message':
                before['messages'] = {'$.message': 'old'}
            baseline.append(before)
            candidate.append(dict(before, **changes))
        baseline.append(self.record(dict(id='missing', method='GET', path='/gone')))
        candidate.append(self.record(dict(id='added', method='GET', path='/new')))
        stdout = self.compare(baseline, candidate, code=1)
        for name in (*variants, 'missing_case', 'added_case'):
            self.assertIn('kind=' + name, stdout)
        self.assertIn('UNAPPROVED', stdout)
        self.assertIn('COMPARE=failed', stdout)
        self.assertNotIn('baseline=old', stdout)
        rules = [{'id': '*', 'kind': name, 'reason': 'approved change'} for name in (*variants, 'missing_case', 'added_case')]
        stdout = self.compare(baseline, candidate, rules)
        self.assertIn('COMPARE=ok', stdout)
        self.assertIn('UNAPPROVED=0', stdout)

    def test_compare_volatility_allow_selectors_and_unused_rules(self):
        before = self.record(dict(id='c1', method='PUT', path='/users/1'), shape={'x': 'num', 'time': 'num'},
                             values={'$.x': 'n:1', '$.time': 'n:100'})
        rerun = dict(before, values={'$.x': 'n:1', '$.time': 'n:101'})
        after = dict(before, status=201, values={'$.x': 'n:2', '$.time': 'n:102'})
        rules = [dict(id='c*', route='PUT /users/*', kind='status', reason='status approved', **{'from': 200, 'to': 201}),
                 dict(route='PUT /users/*', kind='value', path='$.x', reason='value approved'),
                 dict(id='never', kind='text', reason='unused')]
        stdout = self.compare([before], [after], rules, rerun=[rerun])
        self.assertIn('VOLATILE=1', stdout)
        self.assertIn('DIFFS=2 APPROVED=2 UNAPPROVED=0 UNUSED_RULES=1', stdout)
        self.assertIn('UNUSED_RULE', stdout)
        self.assertNotIn('path=$.time', stdout)
        rules[0]['to'] = 202
        self.compare([before], [after], rules, rerun=[rerun], code=1)
        rules[0]['to'] = 201
        rules[0]['route'] = 'GET /users/*'
        self.compare([before], [after], rules, rerun=[rerun], code=1)

    def test_compare_text_body_volatile_between_baselines_is_ignored(self):
        # Páginas HTML com segredo aleatório (debugger) mudam a cada execução: não são regressão.
        before = self.record(dict(id='t1', method='GET', path='/boom'), 404, json=False,
                             content_type='text/html', text_sha='aaa')
        stable = self.record(dict(id='t2', method='GET', path='/nf'), 404, json=False,
                             content_type='text/html', text_sha='same')
        rerun = [dict(before, text_sha='bbb'), stable]
        candidate = [dict(before, text_sha='ccc'), dict(stable, text_sha='changed')]
        stdout = self.compare([before, stable], candidate, rerun=rerun, code=1)
        self.assertNotIn('id=t1', stdout)
        self.assertIn('DIFF id=t2 GET /nf kind=text', stdout)
        self.assertIn('VOLATILE=1', stdout)
        self.assertIn('DIFFS=1 ', stdout)
        content = dict(before, content_type='application/xml', text_sha='ddd')
        stdout = self.compare([before], [content], rerun=rerun[:1], code=1)
        self.assertIn('kind=content_type', stdout)

    def test_compare_candidate_5xx_requires_explicit_rule_even_unchanged(self):
        before = self.record(dict(id='x', method='GET', path='/'), 500)
        self.compare([before], [before], [dict(id='x', kind='status', reason='not enough')], code=1)
        self.compare([before], [before], [dict(id='x', kind='candidate_5xx', reason='explicit')])
        added = dict(before, id='add-server')
        self.compare([], [added], [dict(id='add-*', kind='added_case', reason='not enough')], code=1)

    def test_compare_nested_arrays_and_sensitive_values(self):
        before = self.record(dict(id='x', method='GET', path='/'), shape={'rows': [{'secret': 'str', 'qty': 'num'}]},
                             values={'$.rows[0].qty': 'n:1', '$.password': SECRET})
        after = dict(before, shape={'rows': [{'qty': 'bool'}]}, values={'$.rows[0].qty': 'b:true', '$.password': 'changed'})
        stdout = self.compare([before], [after], code=1)
        self.assertIn('kind=missing_key path=$.rows[].secret', stdout)
        self.assertIn('kind=type path=$.rows[].qty', stdout)
        self.assertNotIn('kind=value', stdout)
        self.compare([before], [before], [dict(kind='type', reason='no selector')], code=2)


    def test_scaffold_all_converters_empty_fields_and_long_ids(self):
        cases = [dict(id='x' * 60, method='PUT', path='/v/1/2.5/12345678-1234-1234-1234-123456789abc',
                      body={'a': [], 'n': None}, expect_status=[200]),
                 dict(id='express', method='GET', path='/users/abc', expect_status=[200])]
        routes = 'PUT /v/<int:id>/<float:n>/<uuid:u>\nGET /users/:id\n'
        self.scaffold(routes, cases)
        result = self.read_lines('cases.jsonl')
        self.assertEqual(sum('not-a-' in c['path'] for c in result), 3)
        self.assertTrue(all(self.module().ID_RE.fullmatch(c['id']) for c in result))
        self.assertFalse(any('express.typed.' in c['id'] for c in result))
        records = [self.record(c) for c in result]
        self.assertIn('TYPED_PARAMS=3/3', self.coverage(routes, records))

    def test_scaffold_rejects_missing_routes_invalid_ids_and_case_keys(self):
        self.put('routes.txt', 'GET /\nGET /other\n')
        self.put('success.jsonl', [dict(id='x', method='GET', path='/')], True)
        self.run_cli('scaffold', '--routes', self.root / 'routes.txt', '--success', self.root / 'success.jsonl',
                     '--out', self.root / 'cases.jsonl', code=2)
        self.put('routes.txt', 'GET /\n')
        for extra in ({'id': 'bad[]'}, {'unknown': SECRET}, {'raw_body': SECRET, 'body': {}}):
            case = dict(id='x', method='GET', path='/')
            case.update(extra)
            self.put('success.jsonl', [case], True)
            self.run_cli('scaffold', '--routes', self.root / 'routes.txt', '--success', self.root / 'success.jsonl',
                         '--out', self.root / 'cases.jsonl', code=2)

    def test_coverage_null_success_body_still_requires_body_categories(self):
        case = dict(id='x', method='POST', path='/', body=None)
        stdout = self.coverage('POST /\n', [self.record(case)], code=1)
        self.assertIn('BODY_ROUTES=1', stdout)
        self.assertIn('MISSING MALFORMED', stdout)
        self.assertIn('MISSING LIST_BODY', stdout)

    def test_coverage_accepts_another_scalar_not_just_scaffold_choice(self):
        cases = [dict(id='x', method='POST', path='/', body={'count': 1})]
        self.scaffold('POST /\n', cases)
        generated = self.read_lines('cases.jsonl')
        for case in generated:
            if case['id'] == 'x.wt.count.scalar':
                case['body']['count'] = 'not numeric'
        self.coverage('POST /\n', [self.record(c) for c in generated])

    def test_message_extraction_ignores_computed_js_and_finds_nested_python_lists(self):
        self.put('src/extra.py', 'def f():\n    return {"items": [{"message": "inside list"}], "error": "123456789012"}, 400\n')
        self.put('src/extra.js', 'res.status(400).json({error: "prefix" + value});\nres.status(409).send({error: "literal send"});\n')
        messages = self.module().extract_messages(self.root / 'src')
        self.assertEqual({m['text'] for m in messages}, {'inside list', '<masked>', 'literal send'})

    def test_derive_refuses_record_request_mismatch(self):
        case = dict(id='x', method='POST', path='/users', body={'a': 1})
        record = self.record(dict(case, path='/other'))
        self.derive([case], [record], {'changes': []}, code=2)

    def test_replay_nested_subset_cap_and_different_sensitive_keys(self):
        module = self.module()
        self.assertFalse(module.subset(True, 1))
        self.assertTrue(module.subset({'x': [{'a': 1}]}, {'x': [{'a': 1, 'b': 2}, 3]}))
        messages, values = module.response_maps({'data': list(range(1100)), 'secret': {'message': SECRET},
                                               'authentication': SECRET})
        self.assertEqual(len(values), 1000)
        self.assertEqual(messages, {})
        self.assertNotIn(SECRET, json.dumps(values))
        self.assertEqual(module.mask_message('x' * 300), 'x' * 200)

    def test_compare_ignores_volatile_list_messages_and_counts_missing_case_values(self):
        before = self.record(dict(id='x', method='GET', path='/'), shape={'errors': ['str']},
                             values={'$.errors': 'len:1', '$.errors[0]': 's:000000000000:a'}, messages={'$.errors': 'a'})
        rerun = dict(before, values={'$.errors': 'len:1', '$.errors[0]': 's:111111111111:a'}, messages={'$.errors': 'b'})
        after = dict(before, values={'$.errors': 'len:1', '$.errors[0]': 's:222222222222:a'}, messages={'$.errors': SECRET})
        stdout = self.compare([before], [after], rerun=[rerun])
        self.assertIn('DIFFS=0', stdout)
        stdout = self.compare([before], [], rerun=[rerun], code=1)
        self.assertIn('VOLATILE=1', stdout)

    def test_compare_path_globs_preserve_array_notation(self):
        before = self.record(dict(id='x', method='GET', path='/'), shape={'items': [{'x': 'num'}]})
        after = dict(before, shape={'items': [{'x': 'str'}]})
        self.compare([before], [after], [dict(id='*', kind='type', path='$.items[].x', reason='approved')])


    def test_replay_invalid_input_does_not_expose_exception_values(self):
        cases = self.put('in.jsonl', [dict(id='x', method='GET', path='/')], True)
        self.run_cli('replay', '--base-url', 'http://127.0.0.1:' + SECRET, '--cases', cases,
                     '--record', self.root / 'out.jsonl', code=2)


    def test_replay_no_redirect_retry_and_handles_truncated_response(self):
        cases = [dict(id='redirect', method='GET', path='/redirect', expect_status=[302]),
                 dict(id='truncated', method='GET', path='/truncate')]
        with self.server() as url:
            stdout = self.run_cli('replay', '--base-url', url, '--cases', self.put('in.jsonl', cases, True),
                                  '--record', self.root / 'out.jsonl', code=1)
        self.assertIn('RESULT=failed REQUESTS=2 FAILED=1', stdout)
        self.assertEqual(len(Handler.seen), 2)
        self.assertEqual([r['status'] for r in self.read_lines('out.jsonl')], [302, 0])

    def test_end_to_end_loopback_pipeline(self):
        routes = 'POST /ok\n'
        self.scaffold(routes, [dict(id='success', method='POST', path='/ok', body={'n': 2, 'items': ['a']}, expect_status=[200])])
        cases = self.read_lines('cases.jsonl')
        with self.server() as url:
            for name in ('b', 'b2', 'c'):
                self.run_cli('replay', '--base-url', url, '--cases', self.root / 'cases.jsonl',
                             '--record', self.root / (name + '.jsonl'))
        baseline, rerun, candidate = [self.read_lines(name + '.jsonl') for name in ('b', 'b2', 'c')]
        self.coverage(routes, baseline)
        self.derive(cases, baseline, {'changes': []})
        self.assertEqual([c['id'] for c in self.read_lines('cand.jsonl')], [c['id'] for c in cases])
        self.compare(baseline, candidate, rerun=rerun)
        self.assertEqual(len(Handler.seen), 3 * len(cases))


    def test_coverage_typed_requirements_do_not_disappear_without_success(self):
        case = dict(id='missing', method='GET', path='/users/1')
        stdout = self.coverage('GET /users/<int:id>\n', [self.record(case, 404)], code=1)
        self.assertIn('TYPED_PARAMS=0/1', stdout)
        self.assertIn('MISSING TYPED_PARAMS', stdout)


    def test_scaffold_unknown_url_is_distinct_from_typed_parameter_probe(self):
        routes = 'GET /<int:id>\n'
        self.scaffold(routes, [dict(id='get', method='GET', path='/1')])
        cases = self.read_lines('cases.jsonl')
        unknown = next(c for c in cases if c['id'] == 'coverage.unknown')
        self.assertGreater(unknown['path'].count('/'), 1)
        self.coverage(routes, [self.record(c) for c in cases])


    def test_value_fingerprint_preserves_full_format(self):
        value = 'Ab12-' * 50
        self.assertTrue(self.module().fingerprint(value).endswith('aa99-' * 50))


if __name__ == '__main__':
    unittest.main()
