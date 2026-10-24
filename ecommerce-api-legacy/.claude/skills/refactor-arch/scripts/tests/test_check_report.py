"""Validação de relatórios com projetos e catálogos sintéticos."""
import sys
sys.dont_write_bytecode = True

from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'check_report.py'
CANARY = 'CANARY_NEVER_DISCLOSE_739152'
QUESTION = 'Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]'


def report(findings=None, counts='CRITICAL: 1 | HIGH: 0 | MEDIUM: 0 | LOW: 0', total=1, files=1, loc=2,
           endpoints=0):
    if findings is None:
        findings = ('### 1. [CRITICAL] Segredo embutido (AP-01)\n'
                    'Arquivo: app.py:1-2\nDescrição: Configuração estática.\n'
                    'Impacto: Exposição.\nRecomendação: Variáveis de ambiente.\n')
    return ('================================\nFASE 1: ANÁLISE DO PROJETO\n'
            '================================\nLinguagem: Python\nFramework: Flask\n'
            'Dependências: Flask\nDomínio: tarefas\nArquitetura: monolito\n'
            'Arquivos: {} arquivos de código, {} linhas\nBanco de dados: nenhum\n'
            'Endpoints: {}\n================================\n\n'.format(files, loc, endpoints) +
            '================================\nRELATÓRIO DE AUDITORIA ARQUITETURAL\n'
            '================================\nProjeto: fixture\nStack: Python\n'
            'Arquivos: 1 analisados | ~2 linhas de código\n\n## Resumo\n' + counts +
            '\n\n## Achados\n\n' + findings +
            '\n## Plano proposto e alterações de contrato\n- Externalizar configuração.\n'
            '\n================================\nTotal: ' + str(total) + ' achados\n'
            '================================\n' + QUESTION + '\n')


class CheckReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put('app.py', 'password = "' + CANARY + '"\nprint("safe")\n')
        self.catalog = self.put('catalog.md', '### AP-01 Segredos\n### AP-02 Acoplamento\n'
                                '### AP-03 Nomes\n### AP-04 Duplicação\n')

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def run_report(self, text, *args):
        target = self.put('report.md', text)
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT),
                                 '--project-root', str(self.root), '--catalog',
                                 str(self.catalog), *map(str, args), str(target)],
                                capture_output=True, text=True)
        self.assertFalse(CANARY in result.stdout + result.stderr, 'A saída contém um segredo sintético.')
        return result

    def test_valid_portuguese_report(self):
        result = self.run_report(report())
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout,
                         'RESULT=ok FINDINGS=1 CRITICAL=1 HIGH=0 MEDIUM=0 LOW=0\n')

    def test_structural_errors_are_rejected(self):
        mutations = [
            (report().replace('FASE 1: ANÁLISE DO PROJETO', 'FASE OMITIDA'), 'phase1'),
            (report().replace('Framework: Flask\n', ''), 'phase1'),
            (report().replace('Domínio: tarefas', 'Domínio: '), 'phase1'),
            (report().replace('RELATÓRIO DE AUDITORIA ARQUITETURAL', 'AUDITORIA'), 'header'),
            (report().replace('Projeto: fixture\n', ''), 'header'),
            (report().replace('## Resumo', '## Sumário'), 'summary'),
            (report().replace('CRITICAL: 1', 'CRITICAL: 2'), 'summary'),
            (report().replace('### 1.', '### 2.'), 'numbering'),
            (report().replace('[CRITICAL]', '[FATAL]'), 'finding'),
            (report().replace('(AP-01)', '(AP-99)'), 'catalog'),
            (report().replace('(AP-01)', ''), 'catalog'),
            (report().replace('Descrição: Configuração estática.\n', ''), 'finding'),
            (report().replace('Total: 1 achados', 'Total: 2 achados'), 'total'),
            (report().replace('## Plano proposto e alterações de contrato', '## Outros'), 'plan'),
            (report() + 'Texto após a confirmação\n', 'confirmation'),
        ]
        for text, kind in mutations:
            with self.subTest(kind=kind, index=mutations.index((text, kind))):
                result = self.run_report(text)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('PROBLEM ' + kind + ':', result.stdout)
                self.assertRegex(result.stdout, r'RESULT=failed PROBLEMS=\d+\n$')

    def test_severity_order_and_multiple_catalog_ids(self):
        first = ('### 1. [LOW] Um achado (AP-01/AP-02)\nArquivo: app.py:1; app.py:2-2\n'
                 'Descrição: Uma falha.\nImpacto: Baixo.\nRecomendação: Corrigir.\n')
        second = first.replace('### 1. [LOW]', '### 2. [HIGH]').replace('AP-01/AP-02', 'AP-03, AP-04')
        result = self.run_report(report(first + second,
                                'CRITICAL: 0 | HIGH: 1 | MEDIUM: 0 | LOW: 1', 2))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('PROBLEM ordering:', result.stdout)
        ordered = first.replace('[LOW]', '[HIGH]') + second.replace('[HIGH]', '[LOW]')
        valid = self.run_report(report(ordered, 'CRITICAL: 0 | HIGH: 1 | MEDIUM: 0 | LOW: 1', 2))
        self.assertEqual(valid.returncode, 0, valid.stdout)

    def test_locations_must_exist_and_fit_within_project_files(self):
        outside = self.root.parent / (self.root.name + '-outside.py')
        outside.write_text('safe=True\n', encoding='utf-8')
        self.addCleanup(outside.unlink)
        (self.root / 'escape.py').symlink_to(outside)
        for location in ['missing.py:1', 'app.py:0', 'app.py:1-3', 'app.py:2-1',
                         'app.py:3', '../' + outside.name + ':1', str(outside) + ':1',
                         'escape.py:1', 'app.py', 'app.py:1; garbage']:
            with self.subTest(location=location):
                result = self.run_report(report().replace('app.py:1-2', location))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('PROBLEM location:', result.stdout)

    def test_sensitive_literals_fail_without_echoing_source_values(self):
        result = self.run_report(report().replace('Exposição.', CANARY + '.'))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('PROBLEM secret: app.py:1', result.stdout)
        self.put('app.py', 'safe=True\nprint("safe")\n')
        for name in ['passwd', 'senha', 'secret', 'access_token', 'api_key', 'apikey',
                     'key', 'private', 'credential', 'smtp_pass', 'card', 'cartao']:
            with self.subTest(name=name):
                self.put('extra.js', 'const ' + name + ' = "' + CANARY + '";\n')
                secret_result = self.run_report(report().replace('Exposição.', CANARY))
                self.assertEqual(secret_result.returncode, 1)
                self.assertIn('PROBLEM secret: extra.js:1', secret_result.stdout)
        self.put('extra.js', 'const password = "short";\n')
        self.assertEqual(self.run_report(report(files=2, loc=3).replace('Exposição.', 'short')).returncode, 0)

    def test_missing_catalog_report_and_root_are_bad_input(self):
        self.catalog.unlink()
        result = self.run_report(report())
        self.assertEqual(result.returncode, 2)
        self.assertIn('PROBLEM input:', result.stdout)
        self.assertNotIn('Traceback', result.stderr)
        self.catalog.write_text('### AP-01 Segredos\n', encoding='utf-8')
        result = self.run_report(report(), '--project-root', self.root / 'missing')
        self.assertEqual(result.returncode, 2)
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--project-root',
                                 str(self.root), '--catalog', str(self.catalog),
                                 str(self.root / 'missing.md')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('RESULT=failed PROBLEMS=1', result.stdout)

    def test_zero_findings_and_all_four_severities(self):
        empty = self.run_report(report('', 'CRITICAL: 0 | HIGH: 0 | MEDIUM: 0 | LOW: 0', 0))
        self.assertEqual(empty.returncode, 0, empty.stdout)
        findings = ''.join('### {}. [{}] Título (AP-0{})\nArquivo: app.py:1\n'
                           'Descrição: Falha.\nImpacto: Risco.\nRecomendação: Corrigir.\n'.format(i, severity, i)
                           for i, severity in enumerate(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'], 1))
        result = self.run_report(report(findings, 'CRITICAL: 1 | HIGH: 1 | MEDIUM: 1 | LOW: 1', 4))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('FINDINGS=4 CRITICAL=1 HIGH=1 MEDIUM=1 LOW=1', result.stdout)
        self.assertFalse(list(self.root.rglob('*.pyc')))

    def test_empty_catalog_and_duplicate_sections_are_not_accepted(self):
        result = self.run_report(report().replace('## Resumo\n', '## Resumo\n## Resumo\n'))
        self.assertEqual(result.returncode, 1)
        self.catalog.write_text('# Empty\n', encoding='utf-8')
        result = self.run_report(report())
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_escaped_source_literal_is_checked_after_decoding(self):
        escaped = ''.join('\\x{:02x}'.format(ord(char)) for char in CANARY)
        self.put('extra.py', '# don\'t confuse the lexer\npassword="' + escaped + '"\n')
        self.put('app.py', 'safe=True\nprint("safe")\n')
        result = self.run_report(report().replace('Exposição.', CANARY))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('PROBLEM secret: extra.py:2', result.stdout)

    def test_multiline_assigned_secret_is_detected_at_literal_line(self):
        self.put('app.py', 'safe=True\nprint("safe")\n')
        self.put('config.py', 'password = (\n  load(\n    "' + CANARY + '"\n  )\n)\n')
        result = self.run_report(report().replace('Exposição.', CANARY))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('PROBLEM secret: config.py:3', result.stdout)

    def test_catalog_default_is_relative_to_script_not_current_directory(self):
        import shutil
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        bundle = Path(outside.name) / 'bundle'
        for name in ['inventory.py', 'check_report.py', 'safe_view.py']:
            target = bundle / 'scripts' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SCRIPT.parent / name, target)
        target = bundle / 'references' / 'anti-patterns.md'
        target.parent.mkdir(parents=True)
        target.write_text('### AP-01 Segredos\n', encoding='utf-8')
        report_path = self.put('report.md', report())
        result = subprocess.run([sys.executable, '-I', '-B', str(bundle / 'scripts/check_report.py'),
                                 '--project-root', str(self.root), str(report_path)],
                                capture_output=True, text=True)
        self.assertFalse(CANARY in result.stdout + result.stderr, 'A saída contém um segredo sintético.')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_catalog_delimiters_number_format_and_section_uniqueness(self):
        invalid = [report().replace('(AP-01)', '(AP-01 + AP-02)'),
                   report().replace('### 1.', '### 01.'),
                   report().replace('## Achados', '## Resumo\nCRITICAL: 1 | HIGH: 0 | MEDIUM: 0 | LOW: 0\n\n## Achados')]
        for index, text in enumerate(invalid):
            with self.subTest(index=index):
                result = self.run_report(text)
                self.assertEqual(result.returncode, 1, result.stdout)
                problems = [line for line in result.stdout.splitlines() if line.startswith('PROBLEM ')]
                self.assertIn('RESULT=failed PROBLEMS=' + str(len(problems)), result.stdout)

    def test_report_from_stdin(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--project-root', str(self.root),
                                 '--catalog', str(self.catalog), '-'], input=report(),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT=ok FINDINGS=1', result.stdout)
        self.assertFalse((self.root / '-').exists())

    def test_phase1_totals_must_match_inventory(self):
        self.put('routes.py', 'from flask import Flask\napp = Flask(__name__)\n'
                 '@app.route("/a")\ndef a(): return "a"\n@app.route("/b", methods=["POST"])\n'
                 'def b(): return "b"\n')
        good = report(files=2, loc=8, endpoints=2)
        self.assertEqual(self.run_report(good).returncode, 0, self.run_report(good).stdout)
        for text in [report(files=3, loc=8, endpoints=2), report(files=2, loc=9, endpoints=2),
                     report(files=2, loc=8, endpoints=3)]:
            with self.subTest(text=text[150:330]):
                result = self.run_report(text)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('PROBLEM phase1:', result.stdout)

    def test_each_catalog_id_belongs_to_one_finding(self):
        first = ('### 1. [CRITICAL] Um achado (AP-01)\nArquivo: app.py:1\n'
                 'Descrição: Uma falha.\nImpacto: Alto.\nRecomendação: Corrigir.\n')
        second = first.replace('### 1.', '### 2.').replace('(AP-01)', '(AP-02/AP-01)')
        result = self.run_report(report(first + second, 'CRITICAL: 2 | HIGH: 0 | MEDIUM: 0 | LOW: 0', 2))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('PROBLEM catalog: duplicate-id=AP-01', result.stdout)

    def test_severity_must_stay_within_one_level_of_catalog(self):
        self.catalog.write_text('## CRITICAL\n### AP-01 Segredos\n## HIGH\n### AP-02 Acoplamento\n'
                                '## MEDIUM\n### AP-03 N+1\n## LOW\n### AP-04 Nomes\n', encoding='utf-8')
        def single(severity, ids):
            return ('### 1. [{}] Achado ({})\nArquivo: app.py:1\nDescrição: Falha.\nImpacto: Risco.\n'
                    'Recomendação: Corrigir.\n').format(severity, ids)
        def counts(severity):
            return ' | '.join('{}: {}'.format(s, int(s == severity)) for s in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])
        for severity, ids, ok in [('CRITICAL', 'AP-01', True), ('HIGH', 'AP-01', True), ('MEDIUM', 'AP-01', False),
                                  ('LOW', 'AP-04', True), ('HIGH', 'AP-04', False), ('MEDIUM', 'AP-04', True),
                                  ('HIGH', 'AP-03/AP-01', True), ('MEDIUM', 'AP-03/AP-01', False)]:
            with self.subTest(severity=severity, ids=ids):
                result = self.run_report(report(single(severity, ids), counts(severity), 1))
                self.assertEqual(result.returncode, 0 if ok else 1, result.stdout)
                if not ok:
                    self.assertIn('PROBLEM severity:', result.stdout)

    def test_unconfirmed_language_and_backticks_in_findings(self):
        for phrase in ['Nenhum uso foi confirmado.', 'O risco não foi confirmado.', 'Sem evidência confirmada.',
                       'Não foi possível confirmar o uso.']:
            with self.subTest(phrase=phrase):
                result = self.run_report(report().replace('Configuração estática.', phrase))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('PROBLEM finding: index=1 unconfirmed-language', result.stdout)
        result = self.run_report(report().replace('Arquivo: app.py:1-2', 'Arquivo: `app.py:1-2`'))
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
