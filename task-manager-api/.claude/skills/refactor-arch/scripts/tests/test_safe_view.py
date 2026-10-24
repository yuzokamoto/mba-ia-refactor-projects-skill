"""Testes de leitura segura com segredos exclusivamente sintéticos."""
import sys
sys.dont_write_bytecode = True

from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'safe_view.py'
CANARY = 'CANARY_NEVER_DISCLOSE_739152'


class SafeViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def run_cli(self, command='show', *args):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), command,
                                 '--project-root', str(self.root), *map(str, args)],
                                capture_output=True, text=True)
        self.assertFalse(CANARY in result.stdout + result.stderr, 'A saída contém um segredo sintético.')
        return result

    def test_show_masks_values_and_preserves_code(self):
        self.put('app.py', 'password = "' + CANARY + '"\n'
                 'name = "Alice"\nprint(name)\n')
        result = self.run_cli('show', 'app.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         '1: password = "<redacted>"\n2: name = "Alice"\n3: print(name)\n')

    def test_redaction_covers_names_urls_cards_pem_and_multiple_values(self):
        source = ('config["API_KEY"] = "' + CANARY + '"; name = "preserved"\n'
                  'login(user="visible", senha="' + CANARY + '")\n'
                  'settings = {"smtp_pass": "' + CANARY + '", "host": "local"}\n'
                  'url = "postgres://user:' + CANARY + '@localhost/db"\n'
                  'number = 1234567890123456; short = 12345\n'
                  'private_key = """-----BEGIN PRIVATE KEY-----\n' + CANARY +
                  '\n-----END PRIVATE KEY-----"""\n'
                  'message = "Do not change this"\n')
        self.put('config.py', source)
        result = self.run_cli('show', 'config.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('config["API_KEY"] = "<redacted>"; name = "preserved"', result.stdout)
        self.assertIn('login(user="visible", senha="<redacted>")', result.stdout)
        self.assertIn('"smtp_pass": "<redacted>", "host": "local"', result.stdout)
        self.assertIn('postgres://<redacted>@localhost/db', result.stdout)
        self.assertIn('number = <redacted>; short = 12345', result.stdout)
        self.assertIn('message = "Do not change this"', result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), len(source.splitlines()))
        self.assertNotIn('1234567890123456', result.stdout)

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.root), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_diff_compares_head_includes_untracked_and_redacts_both_sides(self):
        self.git('init', '-q')
        self.put('app.py', 'password="' + CANARY + '"\nvalue=1\n')
        self.put('deleted.py', 'token="' + CANARY + '"\nold=True\n')
        self.git('add', '.')
        self.git('-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                 'commit', '-qm', 'fixture')
        self.put('app.py', 'password="' + CANARY + '_NEW"\nvalue=2\n')
        self.git('add', 'app.py')
        self.put('app.py', 'password="' + CANARY + '_LATEST"\nvalue=3\n')
        (self.root / 'deleted.py').unlink()
        self.put('new.py', 'api_key="' + CANARY + '"\nnew=True\n')
        before = self.git('status', '--porcelain=v1')
        result = self.run_cli('diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--- a/app.py', result.stdout)
        self.assertIn('+++ b/app.py', result.stdout)
        self.assertIn('-value=1\n+value=3\n', result.stdout)
        self.assertIn('--- /dev/null\n+++ b/new.py', result.stdout)
        self.assertIn('--- a/deleted.py\n+++ /dev/null', result.stdout)
        self.assertIn('password="<redacted>"', result.stdout)
        self.assertEqual(self.git('status', '--porcelain=v1'), before)
        filtered = self.run_cli('diff', 'new.py')
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        self.assertNotIn('app.py', filtered.stdout)
        self.assertIn('new.py', filtered.stdout)

    def test_comments_and_adjacent_literals_cannot_bypass_redaction(self):
        self.put('config.py', '# don\'t parse quotes in comments\n'
                 'password = \'{}\' \'{}\'\n'.format(CANARY, CANARY) +
                 'token = (\n    "' + CANARY + '"\n)\n'
                 'monkey = "visible"\nkeyboard = "visible"\n'
                 'apiKey = `' + CANARY + '`;\n')
        result = self.run_cli('show', 'config.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# don\'t parse quotes in comments', result.stdout)
        self.assertIn('password = \'<redacted>\' \'<redacted>\'', result.stdout)
        self.assertIn('monkey = "visible"', result.stdout)
        self.assertIn('keyboard = "visible"', result.stdout)

    def test_show_range_redacts_before_slicing_and_keeps_crlf(self):
        self.put('key.txt', '-----BEGIN PRIVATE KEY-----\n' + CANARY +
                 '\n-----END PRIVATE KEY-----\nlast\n')
        result = self.run_cli('show', 'key.txt', '--start', 2, '--end', 2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        raw = self.root / 'crlf.py'
        raw.write_bytes(b'name = "visible"\r\nvalue = 2\r\n')
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'show',
                                 '--project-root', str(self.root), 'crlf.py', '--start', '2'],
                                capture_output=True)
        self.assertEqual(result.stdout, b'2: value = 2\r\n')

    def test_invalid_paths_ranges_and_symlink_escapes_fail_closed(self):
        outside = self.root.parent / (self.root.name + '-outside.txt')
        outside.write_text(CANARY, encoding='utf-8')
        self.addCleanup(outside.unlink)
        self.put('ok.py', 'x=1\n')
        (self.root / 'escape.txt').symlink_to(outside)
        for args in [('show', '../' + outside.name), ('show', outside),
                     ('show', 'escape.txt'), ('show', 'missing.py'),
                     ('show', 'ok.py', '--start', 0), ('show', 'ok.py', '--start', 3, '--end', 2),
                     ('show', 'ok.py', '--end', 0), ('diff', outside), ('diff', 'escape.txt')]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)

    def test_diff_without_repository_fails_and_unborn_head_supports_new_files(self):
        self.put('new.py', 'token="' + CANARY + '"\nvalue=1\n')
        self.assertEqual(self.run_cli('diff').returncode, 2)
        self.git('init', '-q')
        result = self.run_cli('diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--- /dev/null\n+++ b/new.py', result.stdout)
        self.assertIn('+value=1', result.stdout)
        self.assertFalse(list(self.root.rglob('*.pyc')))

    def test_show_preserves_missing_final_newline_and_rejects_binary(self):
        self.put('last.py', 'value = 1')
        result = self.run_cli('show', 'last.py')
        self.assertEqual(result.stdout, '1: value = 1')
        (self.root / 'blob.bin').write_bytes(b'\x00binary\xff')
        self.assertEqual(self.run_cli('show', 'blob.bin').returncode, 2)

    def test_untracked_empty_files_and_deleted_empty_files_remain_visible(self):
        self.git('init', '-q')
        self.put('old.py', '')
        self.git('add', '.')
        self.git('-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                 'commit', '-qm', 'fixture')
        (self.root / 'old.py').unlink()
        self.put('empty.py', '')
        result = self.run_cli('diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--- /dev/null\n+++ b/empty.py', result.stdout)
        self.assertIn('--- a/old.py\n+++ /dev/null', result.stdout)

    def test_diff_project_subdirectory_cannot_include_other_projects(self):
        self.git('init', '-q')
        self.put('outside.py', 'password="' + CANARY + '"\n')
        self.put('project/app.py', 'value=1\n')
        self.git('add', '.')
        self.git('-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                 'commit', '-qm', 'fixture')
        self.put('outside.py', 'password="' + CANARY + '_NEW"\n')
        self.put('project/app.py', 'value=2\n')
        original_root = self.root
        self.root = original_root / 'project'
        try:
            result = self.run_cli('diff')
        finally:
            self.root = original_root
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-value=1\n+value=2\n', result.stdout)
        self.assertNotIn('outside.py', result.stdout)

    def test_digit_boundaries_and_unclosed_pem_are_safe(self):
        self.put('values.py', 'a=123456789012\nb=1234567890123456789\n'
                 'c=12345678901\nd=12345678901234567890\n')
        output = self.run_cli('show', 'values.py').stdout
        self.assertIn('1: a=<redacted>', output)
        self.assertIn('2: b=<redacted>', output)
        self.assertIn('3: c=12345678901', output)
        self.assertIn('4: d=12345678901234567890', output)
        self.put('partial.pem', '-----BEGIN PRIVATE KEY-----\n' + CANARY + '\n')
        self.assertEqual(self.run_cli('show', 'partial.pem').returncode, 0)

    def test_nested_defaults_and_javascript_expressions_cannot_expose_values(self):
        self.put('config.js', 'const apiKey = process.env.API_KEY || "' + CANARY + '";\n'
                 'const name = "visible";\nconst settings={token: make("' + CANARY + '", "' + CANARY + '")};\n'
                 'login(password = wrap(inner("' + CANARY + '")), user="visible");\n')
        result = self.run_cli('show', 'config.js')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('const name = "visible"', result.stdout)
        self.assertIn('user="visible"', result.stdout)
        self.put('config.py', 'password = os.getenv("PASSWORD", "' + CANARY + '")\n'
                 'token = (\n  # comentário sintético\n  wrap("' + CANARY + '")\n)\n'
                 'url = "password=not_a_real_secret"\n')
        result = self.run_cli('show', 'config.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('url = "password=not_a_real_secret"', result.stdout)

    def test_camel_case_and_kebab_secret_names_are_redacted(self):
        # Chaves camelCase (dbPass, paymentGatewayKey) já vazaram em projeto real.
        self.put('utils.js', 'const config = {\n'
                 '    dbUser: "visible_user",\n'
                 '    dbPass: "' + CANARY + '",\n'
                 '    paymentGatewayKey: "' + CANARY + '",\n'
                 "    smtpPassword: '" + CANARY + "',\n"
                 '    port: 3000\n};\n'
                 "const apiKey = '" + CANARY + "';\n"
                 'headers = {"x-api-key": "' + CANARY + '", "x-request-id": "visible-id"}\n'
                 'monkeyBusiness = "visible-monkey"\nkeys = "visible-keys"\n')
        result = self.run_cli('show', 'utils.js')
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ['dbUser: "visible_user"', 'dbPass: "<redacted>"', 'paymentGatewayKey: "<redacted>"',
                         "smtpPassword: '<redacted>'", 'port: 3000', '"x-request-id": "visible-id"',
                         'monkeyBusiness = "visible-monkey"', 'keys = "visible-keys"']:
            self.assertIn(expected, result.stdout)

    def test_sensitive_call_arguments_are_hidden_but_structure_kept(self):
        self.put('auth.py', 'user.set_password("' + CANARY + '")\n'
                 'digest = hashlib.md5("' + CANARY + '".encode("utf-8")).hexdigest()\n'
                 'user.set_password(\n    "' + CANARY + '"\n)\n'
                 "h = crypto.createHash('md5').update(pwd).digest('hex')\n"
                 "const hashed = badCrypto('" + CANARY + "', require('./utils'));\n"
                 'stored = generate_password_hash(request.json["senha"])\n'
                 'log(encrypt(`card ${cc}`))\n'
                 'return jsonify({"error": "visible message"}), 401\n')
        result = self.run_cli('show', 'auth.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ['user.set_password("<redacted>")', 'hashlib.md5("<redacted>".encode("utf-8"))',
                         "createHash('md5')", "digest('hex')", "require('./utils')",
                         'generate_password_hash(request.json["senha"])', 'encrypt(`card ${cc}`)',
                         '"error": "visible message"']:
            self.assertIn(expected, result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 10)

    def test_secret_comparisons_and_defaults_hide_values_keep_env_names(self):
        self.put('login.py', 'if senha == "' + CANARY + '":\n    pass\n'
                 'if (dbPass !== "' + CANARY + '") {}\n'
                 'password = os.getenv("DB_PASSWORD", "' + CANARY + '")\n'
                 'secret = data.get("secret_field") or "' + CANARY + '"\n'
                 'let pwd = p || "' + CANARY + '";\n'
                 'if status == "visible-status":\n    pass\n')
        result = self.run_cli('show', 'login.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ['senha == "<redacted>"', 'dbPass !== "<redacted>"',
                         'os.getenv("DB_PASSWORD", "<redacted>")', 'data.get("secret_field") or "<redacted>"',
                         'p || "<redacted>"', 'status == "visible-status"']:
            self.assertIn(expected, result.stdout)

    def test_seed_rows_bound_to_secret_insert_columns_are_redacted(self):
        # Senhas de seed em tuplas posicionais não têm nome: a coluna vem do INSERT com placeholders.
        self.put('database.py',
                 'produtos = [\n    ("Mouse", "Sem fio", 99.9, 10, "acessorios"),\n]\n'
                 'usuarios = [\n'
                 '    ("Admin", "admin@example.test", "' + CANARY + '", "admin"),\n'
                 '    ("Maria Silva", "maria@example.test", "' + CANARY + '2", "cliente"),\n'
                 ']\n'
                 'cursor.executemany(\n'
                 '    "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",\n'
                 '    usuarios\n)\n'
                 'cursor.execute("INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",\n'
                 '               (nome, email, senha, tipo))\n'
                 'jsonify("a", "b", "visible-call-arg", "d")\n')
        result = self.run_cli('show', 'database.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('5:     ("Admin", "admin@example.test", "<redacted>", "admin"),\n', result.stdout)
        self.assertIn('6:     ("Maria Silva", "maria@example.test", "<redacted>", "cliente"),\n', result.stdout)
        self.assertIn('2:     ("Mouse", "Sem fio", 99.9, 10, "acessorios"),\n', result.stdout)
        self.assertIn('(nome, email, senha, tipo))\n', result.stdout)
        self.assertIn('"visible-call-arg"', result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 14)

    def test_inline_sql_values_of_secret_columns_are_redacted(self):
        self.put('src/app.js',
                 "db.run(\"INSERT INTO users (name, email, pass) VALUES ('Ana', 'ana@example.test', '"
                 + CANARY + "')\");\n"
                 "db.run(\"INSERT INTO users (name, pass) VALUES ('Bob', '" + CANARY + "'), ('Eve', '"
                 + CANARY + "')\");\n"
                 "db.run(`UPDATE users SET pass = '" + CANARY + "' WHERE name = 'Ana'`);\n"
                 "db.run(\"INSERT INTO courses (title, price) VALUES ('Clean Code', 997.00)\");\n"
                 "db.run(\"INSERT INTO users (name, pass) VALUES ('Short', '123')\");\n")
        result = self.run_cli('show', 'src/app.js')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("VALUES ('Ana', 'ana@example.test', '<redacted>')", lines[0])
        self.assertIn("VALUES ('Bob', '<redacted>'), ('Eve', '<redacted>')", lines[1])
        self.assertIn("SET pass = '<redacted>' WHERE name = 'Ana'", lines[2])
        self.assertIn("VALUES ('Clean Code', 997.00)", lines[3])
        self.assertIn("VALUES ('Short', '<redacted>')", lines[4])
        import importlib.util
        spec = importlib.util.spec_from_file_location('safe_view_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (self.root / 'src/app.js').read_text(encoding='utf-8')
        self.assertIn(CANARY, {value for value, _ in module.sensitive_literals(source)})

    def test_sensitive_literals_are_exactly_the_hidden_values(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('safe_view_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = ('dbPass = "' + CANARY + '1"\nuser.set_password("' + CANARY + '2")\n'
                'return jsonify({"error": "Invalid password message"}), 401\n'
                'password = os.getenv("DB_PASSWORD_NAME", "' + CANARY + '3")\n')
        values = {value for value, _ in module.sensitive_literals(text)}
        self.assertEqual({v for v in values if v.startswith(CANARY)}, {CANARY + '1', CANARY + '2', CANARY + '3'})
        self.assertNotIn('Invalid password message', values)
        self.assertNotIn('DB_PASSWORD_NAME', values)


if __name__ == '__main__':
    unittest.main(verbosity=2)
