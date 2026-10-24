"""Testes isolados da preparação do ambiente descartável."""
import sys
sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'sandbox.py'
SECRET = 'CANARY-SANDBOX-SECRET-94abcd'


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.tmp = self.base / 'tmp'
        self.tmp.mkdir()
        self.env = dict(os.environ, TMPDIR=str(self.tmp))
        self.root = None
        self.addCleanup(self.finish)

    def finish(self):
        if self.root and self.root.exists():
            self.cli('finish', '--run-root', self.root, expected=None)

    def put(self, name, text='fixture'):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def cli(self, *args, expected=0, env=None):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *map(str, args)],
                                env=env or self.env, cwd=self.base, capture_output=True,
                                text=True, timeout=15)
        self.assertFalse(SECRET in result.stdout + result.stderr, 'Vazamento de segredo')
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def init(self):
        output = self.cli('init', '--project-root', self.project)
        self.root = Path(next(line[9:] for line in output.splitlines() if line.startswith('RUN_ROOT=')))
        return output

    def copy(self, name='app', *args):
        self.cli('copy', '--run-root', self.root, '--name', name, *args)
        return self.root / 'copies' / name

    def test_init_fingerprints_and_permissions(self):
        self.put('data.db')
        self.put('instance/x.db')
        self.put('instance/config.txt')
        self.put('node_modules/ignored.db')
        output = self.init()
        self.assertIn('DATA_STORES=3', output)
        self.assertIn('DATA_STORE instance/config.txt', output)
        state = json.loads((self.root / 'state.json').read_text())
        self.assertIn('project_root', state)
        for name in ('data.db', 'instance/x.db', 'instance/config.txt'):
            path = self.project / name
            self.assertEqual(state['data_stores'][name], {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'size': path.stat().st_size, 'mode': path.stat().st_mode & 0o777})
            self.assertFalse(state['data_stores'][name]['sha256'] in output,
                             'Fingerprint não deve aparecer na saída')
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        for name in ('home', 'tmp', 'logs', 'copies'):
            self.assertTrue((self.root / name).is_dir())
        self.assertIn('DATA_GUARD=ok', self.cli('check', '--run-root', self.root))

    def test_init_refuses_project_tmp_and_bad_project(self):
        self.cli('init', '--project-root', self.project, expected=2,
                 env=dict(self.env, TMPDIR=str(self.project)))
        self.assertEqual(list(self.project.iterdir()), [])
        self.cli('init', '--project-root', self.base / 'absent', expected=2)

    def test_copy_exclusions_dependencies_and_names(self):
        for name in ('main.py', 'data.db', 'nested/a.sqlite3', 'nested/a.db-wal',
                     'instance/config.py', '.git/config', '.agents/x', '.claude/x',
                     '__pycache__/x.pyc', 'reports/x', '.handoff/x', '.worktrees/x',
                     'nested/a.pyc', '.pytest_cache/x', '.venv/bin/python', 'node_modules/x'):
            self.put(name)
        self.init()
        dest = self.copy()
        self.assertTrue((dest / 'main.py').is_file())
        for name in ('data.db', 'instance', '.git', '.agents', '.claude', '__pycache__',
                     'reports', '.handoff', '.worktrees', '.pytest_cache', 'nested/a.sqlite3',
                     'nested/a.db-wal', 'nested/a.pyc'):
            self.assertFalse((dest / name).exists(), name)
        for name in ('.venv', 'node_modules'):
            self.assertTrue((dest / name).is_symlink())
            self.assertEqual((dest / name).readlink(), self.project / name)
        self.cli('copy', '--run-root', self.root, '--name', 'app', expected=2)
        for name in ('../escape', '-invalid', 'a' * 65):
            self.cli('copy', '--run-root', self.root, '--name=' + name, expected=2)
        self.copy('second', '--from', dest)

    def test_ref_uses_committed_subdirectory(self):
        self.project = self.base / 'repo' / 'subdir'
        self.project.mkdir(parents=True)
        repo = self.project.parent
        def git(*args):
            result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
            self.assertEqual(result.returncode, 0)
        git('init', '-q')
        self.put('app.txt', 'committed')
        self.put('data.db')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
        self.put('app.txt', 'uncommitted')
        self.put('node_modules/x')
        self.init()
        dest = self.copy('baseline', '--ref', 'HEAD')
        self.assertEqual((dest / 'app.txt').read_text(), 'committed')
        self.assertFalse((dest / 'data.db').exists())
        self.assertTrue((dest / 'node_modules').is_symlink())
    def run_python(self, source, expected=0, *options):
        return self.cli('run', '--run-root', self.root, '--name', 'app', *options,
                        '--', sys.executable, '-c', source, expected=expected)

    def test_run_copy_environment_and_redaction(self):
        self.put('app.py', 'pass')
        self.init()
        dest = self.copy()
        output = self.run_python(
            'import os,pathlib; print(os.getcwd()); '
            'assert pathlib.Path(os.environ["HOME"]).name == "home"; '
            'assert pathlib.Path(os.environ["TMPDIR"]).name == "tmp"; '
            'assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"; '
            'assert os.environ["CUSTOM_VALUE"] == "' + SECRET + '"; '
            'print(\'password = "' + SECRET + '"\'); '
            'pathlib.Path("created.txt").write_text("copy")', 0,
            '--env', 'CUSTOM_VALUE=' + SECRET)
        self.assertIn(str(dest), output)
        self.assertIn('ENV_KEYS=CUSTOM_VALUE', output)
        self.assertIn('DATA_GUARD=ok', output)
        self.assertIn('EXIT=0', output)
        self.assertTrue((dest / 'created.txt').exists())
        self.assertFalse((self.project / 'created.txt').exists())
        self.assertEqual(len(list((self.root / 'logs').glob('app-run-*.log'))), 1)

    def test_run_database_violation(self):
        database = self.put('data.db')
        self.init()
        self.copy()
        output = self.run_python('from pathlib import Path; Path(' + repr(str(database)) +
                                 ').write_text("modified")', 1)
        self.assertIn('VIOLATION data_store_changed data.db', output)
        self.assertIn('DATA_GUARD=violation', output)
        self.assertIn('FINISH=failed', self.cli('finish', '--run-root', self.root, expected=1))
        self.assertFalse(self.root.exists())

    def test_run_project_cache_violation(self):
        self.init()
        self.copy()
        output = self.run_python('from pathlib import Path; p=Path(' + repr(str(self.project)) +
                                 ')/"__pycache__"; p.mkdir(); (p/"x.pyc").write_bytes(b"x")', 1)
        self.assertIn('VIOLATION project_file_added __pycache__', output)
        self.assertIn('VIOLATION project_file_added __pycache__/x.pyc', output)

    def test_check_missing_new_and_mode_changed_data(self):
        path = self.put('data.db')
        self.put('old.sqlite')
        self.init()
        path.chmod(0o600 if path.stat().st_mode & 0o777 != 0o600 else 0o644)
        (self.project / 'old.sqlite').unlink()
        self.put('new.db-wal')
        output = self.cli('check', '--run-root', self.root, expected=1)
        for line in ('data_store_changed data.db', 'data_store_missing old.sqlite',
                     'data_store_new new.db-wal'):
            self.assertIn('VIOLATION ' + line, output)

    def test_run_exit_failure_and_output_limit(self):
        self.init()
        self.copy()
        output = self.run_python('print("discarded-first-line"); '
                                 '[print("line-%s" % i) for i in range(50)]; exit(7)', 1)
        self.assertIn('EXIT=7', output)
        self.assertNotIn('discarded-first-line', output)
        self.assertIn('line-49', output)
        self.assertIn('DATA_GUARD=ok', output)

    def test_timeout_kills_descendant(self):
        self.init()
        dest = self.copy()
        output = self.run_python(
            'import subprocess,time,pathlib; p=subprocess.Popen(["sleep","30"]); '
            'pathlib.Path("child.pid").write_text(str(p.pid)); time.sleep(30)',
            1, '--timeout', '0.3')
        self.assertIn('TIMEOUT=yes', output)
        pid = int((dest / 'child.pid').read_text())
        self.assert_process_stopped(pid)

    def assert_process_stopped(self, pid):
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            proc_stat = Path('/proc') / str(pid) / 'stat'
            if proc_stat.exists() and proc_stat.read_text().split(') ', 1)[1].startswith('Z'):
                return
            time.sleep(0.03)
        self.fail('Processo descendente permaneceu ativo')

    def test_bad_input_does_not_print_values(self):
        self.init()
        self.copy()
        for options in (('--env', 'INVALID'), ('--env', 'A-B=' + SECRET),
                        ('--timeout', '0'), ('--timeout', 'nan')):
            self.run_python('pass', 2, *options)
        self.cli('run', '--run-root', self.root, '--name', 'app', '--', expected=2)
        self.cli('check', '--run-root', self.base, expected=2)
    def free_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]

    def serve(self, port, server, client=None, expected=0, options=()):
        if client is None:
            client = [sys.executable, '-c',
                      'import os,urllib.request; '
                      'assert os.getcwd() == ' + repr(str(self.base)) + '; '
                      'assert "CUSTOM_ONLY" not in os.environ; '
                      'print(urllib.request.urlopen(os.environ["BASE_URL"]).status)']
        return self.cli('serve', '--run-root', self.root, '--name', 'app', '--port', port,
                        *options, '--', *server, '--then', '--', *client, expected=expected)

    def test_serve_ready_http_error_caller_cwd_and_free(self):
        self.init()
        self.copy()
        port = self.free_port()
        output = self.serve(port, [sys.executable, '-m', 'http.server', str(port),
                                   '--bind', '127.0.0.1'],
                            options=('--ready', '/not-found', '--env', 'CUSTOM_ONLY=' + SECRET))
        for line in ('SERVER_READY=yes', 'CLIENT_EXIT=0', 'PORT_FREE=yes',
                     'SERVER_LOG=', 'DATA_GUARD=ok'):
            self.assertIn(line, output)
        with socket.socket() as listener:
            self.assertNotEqual(listener.connect_ex(('127.0.0.1', port)), 0)

    def test_serve_timeout_and_early_exit(self):
        self.init()
        self.copy()
        for server in ([sys.executable, '-c', 'import time; time.sleep(30)'],
                       [sys.executable, '-c', 'print(\'password = "' + SECRET + '"\'); exit(3)']):
            output = self.serve(self.free_port(), server, expected=1, options=('--timeout', '0.2'))
            self.assertIn('SERVER_READY=no', output)
            self.assertIn('DATA_GUARD=ok', output)

    def test_serve_busy_does_not_start_command(self):
        self.init()
        dest = self.copy()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            output = self.serve(port, [sys.executable, '-c',
                                      'from pathlib import Path; Path("marker").touch()'], expected=1)
            self.assertIn('PORT_BUSY=' + str(port), output)
        self.assertFalse((dest / 'marker').exists())

    def test_serve_client_failure_redaction_and_limit(self):
        self.init()
        self.copy()
        port = self.free_port()
        output = self.serve(port, [sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                            client=[sys.executable, '-c',
                                    'print(\'password = "' + SECRET + '"\'); '
                                    '[print("client-line-%s" % i) for i in range(220)]; exit(4)'], expected=1)
        self.assertIn('CLIENT_EXIT=4', output)
        self.assertIn('PORT_FREE=yes', output)
        # O resumo do cliente (RESULT=, COMPARE=) fica no fim: mostra o final e conta o que omitiu.
        self.assertIn('client-line-219\n', output)
        self.assertIn('client-line-20\n', output)
        self.assertNotIn('client-line-19\n', output)
        self.assertIn('CLIENT_OMITTED_LINES=21\n', output)

    def test_syntax_memory_and_dependency_skips(self):
        self.put('good.py', 'answer = 42\n')
        self.put('bad.py', 'x = 1\nif :\n')
        self.put('.venv/bad.py', 'if :')
        self.put('node_modules/bad.js', 'const = ;')
        self.init()
        dest = self.copy()
        output = self.cli('syntax', '--run-root', self.root, '--name', 'app', expected=1)
        self.assertIn('SYNTAX_ERROR bad.py:2', output)
        self.assertIn('SYNTAX=failed FILES=2', output)
        (dest / 'bad.py').unlink()
        self.assertIn('SYNTAX=ok FILES=1', self.cli('syntax', '--run-root', self.root, '--name', 'app'))
        self.assertEqual(list(dest.rglob('*.pyc')), [])
        self.assertEqual(list(self.project.rglob('*.pyc')), [])

    def test_syntax_javascript(self):
        if not __import__('shutil').which('node'):
            self.skipTest('Node não instalado')
        self.put('good.mjs', 'const answer = 42;\n')
        self.put('bad.cjs', 'const = ;\n')
        self.init()
        dest = self.copy()
        output = self.cli('syntax', '--run-root', self.root, '--name', 'app', expected=1)
        self.assertIn('SYNTAX_ERROR bad.cjs:1', output)
        (dest / 'bad.cjs').unlink()
        self.assertIn('SYNTAX=ok FILES=1', self.cli('syntax', '--run-root', self.root, '--name', 'app'))

    def test_finish_kills_recorded_leftover_server(self):
        self.init()
        dest = self.copy()
        port = self.free_port()
        self.run_python('import subprocess,pathlib; p=subprocess.Popen([' + repr(sys.executable) +
                        ',"-m","http.server",' + repr(str(port)) + ',"--bind","127.0.0.1"]); '
                        'pathlib.Path("server.pid").write_text(str(p.pid))')
        pid = int((dest / 'server.pid').read_text())
        output = self.cli('finish', '--run-root', self.root)
        self.assertIn('FINISH=ok', output)
        self.assertFalse(self.root.exists())
        self.assert_process_stopped(pid)
    def test_guard_unreadable_store_still_fails_and_finish_removes_root(self):
        database = self.put('data.db')
        self.init()
        self.copy()
        output = self.run_python('from pathlib import Path; p=Path(' + repr(str(database)) +
                                 '); p.unlink(); p.symlink_to("missing-target")', 1)
        self.assertIn('DATA_GUARD=violation', output)
        output = self.cli('finish', '--run-root', self.root, expected=1)
        self.assertIn('FINISH=failed', output)
        self.assertFalse(self.root.exists())

    def test_malformed_state_is_bad_input(self):
        self.init()
        (self.root / 'state.json').write_text('[]')
        self.cli('check', '--run-root', self.root, expected=2)
        self.cli('finish', '--run-root', self.base, expected=2)

    def test_copy_rejects_escaping_links(self):
        self.put('main.py', 'pass')
        (self.project / 'escape').symlink_to('../outside')
        self.init()
        self.cli('copy', '--run-root', self.root, '--name', 'unsafe', expected=2)
        self.assertFalse((self.root / 'copies' / 'unsafe').exists())
        for args in (['init', '-q'], ['add', '.'],
                     ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                      'commit', '-qm', 'fixture']):
            subprocess.run(['git', '-C', str(self.project), *args], check=True, capture_output=True)
        self.cli('copy', '--run-root', self.root, '--name', 'unsafe-ref', '--ref', 'HEAD', expected=2)
        self.assertFalse((self.root / 'copies' / 'unsafe-ref').exists())

    def test_syntax_without_node(self):
        self.put('good.py', 'x = 1')
        self.put('unchecked.js', 'const = ;')
        self.init()
        self.copy()
        output = self.cli('syntax', '--run-root', self.root, '--name', 'app',
                          env=dict(self.env, PATH=''))
        self.assertIn('NODE=missing', output)
        self.assertIn('SYNTAX=ok', output)

    def test_run_modified_project_file(self):
        source = self.put('main.py', 'pass')
        self.init()
        self.copy()
        output = self.run_python('from pathlib import Path; Path(' + repr(str(source)) +
                                 ').write_text("answer = 1")', 1)
        self.assertIn('VIOLATION project_file_changed main.py', output)

    def test_serve_guard_after_client(self):
        target = self.put('data.db')
        self.init()
        self.copy()
        port = self.free_port()
        output = self.serve(port, [sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                            client=[sys.executable, '-c', 'from pathlib import Path; Path(' +
                                    repr(str(target)) + ').write_text("changed")'], expected=1)
        self.assertIn('CLIENT_EXIT=0', output)
        self.assertIn('DATA_GUARD=violation', output)
        self.assertIn('PORT_FREE=yes', output)
    def test_environment_overrides_are_applied_last(self):
        self.init()
        self.copy()
        override = str(self.root / 'home' / 'alternate')
        output = self.run_python('import os; assert os.environ["HOME"] == ' + repr(override),
                                 0, '--env', 'HOME=' + override)
        self.assertIn('ENV_KEYS=HOME', output)

    def test_repeated_runs_have_one_final_guard(self):
        self.init()
        self.copy()
        self.run_python('pass')
        output = self.run_python('pass')
        self.assertEqual(output.count('DATA_GUARD='), 1)
        self.assertTrue((self.root / 'logs' / 'app-run-2.log').exists())

    def test_redaction_before_log_tail_and_bare_env_values(self):
        self.init()
        self.copy()
        output = self.run_python('import os; print(os.environ["CUSTOM_VALUE"]); '
                                 'print("-----BEGIN PRIVATE KEY-----"); '
                                 '[print("padding") for i in range(45)]; '
                                 'print("' + SECRET + '"); print("-----END PRIVATE KEY-----")',
                                 0, '--env', 'CUSTOM_VALUE=' + SECRET)
        self.assertIn('EXIT=0', output)
    def test_snapshot_ignores_environment_mount_points(self):
        # Sandboxes de agentes montam diretórios vazios (.codex, .aws) no projeto a cada comando,
        # com mtime novo; não são arquivos do projeto e não podem virar violação.
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location('sandbox_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.put('main.py', 'pass')
        self.put('.aws/inner.txt')
        self.put('.codex', '')
        mounts = {str(self.project / '.aws'), str(self.project / '.codex')}
        real_ismount = os.path.ismount
        with mock.patch('os.path.ismount', lambda path: str(path) in mounts or real_ismount(path)):
            names = set(module.snapshot(self.project))
        self.assertIn('main.py', names)
        self.assertFalse({'.aws', '.aws/inner.txt', '.codex'} & names, names)

    def test_snapshot_starts_immediately_before_each_command(self):
        self.init()
        self.copy()
        self.run_python('pass')
        self.put('intentional-edit.py', 'answer = 42')
        output = self.run_python('pass')
        self.assertIn('DATA_GUARD=ok', output)

    def test_serve_timeout_is_readiness_deadline(self):
        self.init()
        self.copy()
        port = self.free_port()
        output = self.serve(port, [sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                            client=[sys.executable, '-c', 'import time; time.sleep(0.7)'],
                            options=('--timeout', '0.5'))
        self.assertIn('CLIENT_EXIT=0', output)
    def test_removed_original_project_is_violation_not_input_error(self):
        self.put('main.py', 'pass')
        self.put('data.db')
        self.init()
        self.copy()
        output = self.run_python('import shutil; shutil.rmtree(' + repr(str(self.project)) + ')', 1)
        self.assertIn('VIOLATION data_store_missing data.db', output)
        self.assertIn('VIOLATION project_file_changed main.py', output)
        self.assertIn('FINISH=failed', self.cli('finish', '--run-root', self.root, expected=1))
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
