"""Verificação mecânica do relatório arquitetural em português."""
import sys
sys.dont_write_bytecode = True

import argparse
import importlib.util
from pathlib import Path
import re

SEVERITIES = ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
FINDING_RE = re.compile(r'^### (\d+)\. \[(CRITICAL|HIGH|MEDIUM|LOW)\] (.+)$', re.MULTILINE)
QUESTION = 'Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]'
# Achado é problema confirmado; dúvidas vão para a linha "Cobertura" do plano.
UNCONFIRMED_RE = re.compile(r'\b(?:não|nao)\s+(?:foi\s+|está\s+|é\s+|pôde\s+ser\s+)?(?:possível\s+)?confirm'
                            r'|\bnenhum\w*\b[^.\n]*\bconfirmad|\bsem\s+evid[êe]ncia|\bunconfirmed'
                            r'|\bnot\s+confirmed', re.IGNORECASE)


def section(text, heading):
    """Extrai uma seção de nível dois sem consumir a próxima."""
    match = re.search(r'^' + re.escape(heading) + r'[ \t]*\n(.*?)(?=^## |\Z)',
                      text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


def load_helper(name):
    """Carrega somente módulos auxiliares distribuídos junto ao verificador."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVENTORY = load_helper('inventory')
SAFE_VIEW = load_helper('safe_view')


def catalog_severities(catalog):
    """Mapeia cada AP à severidade da seção '## <SEVERIDADE>' em que aparece."""
    severities, current = {}, None
    for line in catalog.splitlines():
        heading = re.match(r'^## (CRITICAL|HIGH|MEDIUM|LOW)\b', line)
        if heading:
            current = heading.group(1)
        elif line.startswith('## '):
            current = None
        ap = re.match(r'^### (AP-\d{2,})\b', line)
        if ap and current:
            severities[ap.group(1)] = current
    return severities


def phase1_totals(phase, root, problem):
    """Os totais da Fase 1 são os do inventário mecânico, não estimativas."""
    data = INVENTORY.collect(root)
    files, loc, endpoints = len(data['files']), data['loc'], len(data['endpoints'])
    files_line = re.search(r'^Arquivos:[ \t]*(.*)$', phase, re.MULTILINE)
    if files_line:
        numbers = [int(n) for n in re.findall(r'\d+', files_line.group(1).replace('.', ''))]
        if not numbers or numbers[0] != files:
            problem('phase1', 'files-mismatch-inventory={}'.format(files))
        if loc not in numbers[1:]:
            problem('phase1', 'loc-mismatch-inventory={}'.format(loc))
    endpoints_line = re.search(r'^Endpoints:[ \t]*(\d+)', phase, re.MULTILINE)
    if re.search(r'^Endpoints:', phase, re.MULTILINE) and (
            not endpoints_line or int(endpoints_line.group(1)) != endpoints):
        problem('phase1', 'endpoints-mismatch-inventory={}'.format(endpoints))


def validate(text, catalog, root):
    problems = []

    def problem(kind, detail):
        problems.append((kind, detail))

    phase_title = 'FASE 1: ANÁLISE DO PROJETO'
    report_title = 'RELATÓRIO DE AUDITORIA ARQUITETURAL'
    phase_start, header_start = text.find(phase_title), text.find(report_title)
    phase = text[phase_start:header_start] if 0 <= phase_start < header_start else ''
    fields = ('Linguagem', 'Framework', 'Dependências', 'Domínio', 'Arquitetura',
              'Arquivos', 'Banco de dados', 'Endpoints')
    if not phase:
        problem('phase1', 'missing-analysis-block')
    for field in fields:
        if not re.search(r'^' + re.escape(field) + r':[ \t]*\S[^\n]*$', phase, re.MULTILINE):
            problem('phase1', 'missing-or-empty-field=' + field)
    if phase:
        phase1_totals(phase, root, problem)
    header = text[header_start:].split('## Resumo')[0] if header_start >= 0 else ''
    if not header:
        problem('header', 'missing-report-header')
    for field in ('Projeto', 'Stack', 'Arquivos'):
        if not re.search(r'^' + field + r':[ \t]*\S[^\n]*$', header, re.MULTILINE):
            problem('header', 'missing-or-empty-field=' + field)
    for heading, kind in [('## Resumo', 'summary'), ('## Achados', 'finding'),
                          ('## Plano proposto e alterações de contrato', 'plan')]:
        if len(re.findall(r'^' + re.escape(heading) + r'[ \t]*$', text, re.MULTILINE)) > 1:
            problem(kind, 'duplicate-section')
    findings_section = section(text, '## Achados')
    if findings_section is None:
        problem('finding', 'missing-findings-section')
        findings_section = ''
    headings = list(re.finditer(r'^### [^\n]*$', findings_section, re.MULTILINE))
    findings = []
    catalog_ids = set(re.findall(r'^### (AP-\d{2,})\b', catalog, re.MULTILINE))
    severity_of = catalog_severities(catalog)
    used_ids = {}
    for index, heading in enumerate(headings, 1):
        match = FINDING_RE.fullmatch(heading.group())
        if not match:
            problem('finding', 'invalid-heading-index=' + str(index))
            continue
        findings.append(match)
        if match.group(1) != str(index):
            problem('numbering', 'expected-index=' + str(index))
        body_end = headings[index].start() if index < len(headings) else len(findings_section)
        body = findings_section[heading.end():body_end]
        for field in ('Arquivo', 'Descrição', 'Impacto', 'Recomendação'):
            if not re.search(r'^' + field + r':[ \t]*\S[^\n]*$', body, re.MULTILINE):
                problem('finding', 'index={} missing-or-empty-field={}'.format(index, field))
        locations = re.findall(r'^Arquivo:[ \t]*(.*)$', body, re.MULTILINE)
        for location_line in locations:
            for location in location_line.split(';'):
                location = location.strip().strip('`').strip()
                reference = re.fullmatch(r'(.+?):(\d+)(?:-(\d+))?', location)
                try:
                    if not reference or Path(reference.group(1)).is_absolute():
                        raise ValueError('invalid-reference')
                    path = SAFE_VIEW.checked_path(root, reference.group(1))
                    length = len(path.read_text(encoding='utf-8').splitlines())
                    start = int(reference.group(2))
                    end = int(reference.group(3) or start)
                    if not 1 <= start <= end <= length:
                        raise ValueError('invalid-range')
                except (OSError, ValueError, UnicodeError):
                    problem('location', 'invalid-source-reference-index=' + str(index))
        citation = re.search(r'\((AP-\d{2,}(?:\s*[/,]\s*AP-\d{2,})*)\)\s*$', match.group(3))
        ids = re.findall(r'AP-\d{2,}', citation.group(1)) if citation else []
        if not ids or any(ap not in catalog_ids for ap in ids):
            problem('catalog', 'missing-or-unknown-id-index=' + str(index))
        for ap in ids:
            if ap in used_ids and used_ids[ap] != index:
                problem('catalog', 'duplicate-id={} index={}'.format(ap, index))
            used_ids.setdefault(ap, index)
        known = [SEVERITIES.index(severity_of[ap]) for ap in ids if ap in severity_of]
        if known and abs(SEVERITIES.index(match.group(2)) - min(known)) > 1:
            problem('severity', 'index={} catalog={}'.format(index, SEVERITIES[min(known)]))
        if UNCONFIRMED_RE.search(body) or UNCONFIRMED_RE.search(match.group(3)):
            problem('finding', 'index={} unconfirmed-language'.format(index))
    order = [SEVERITIES.index(match.group(2)) for match in findings]
    if order != sorted(order):
        problem('ordering', 'findings-must-follow-severity-order')
    for source in INVENTORY.project_files(root):
        content = source.read_text(encoding='utf-8', errors='replace')
        leaked = {line for value, line in SAFE_VIEW.sensitive_literals(content) if value in text}
        for line in sorted(leaked):
            problem('secret', '{}:{}'.format(source.relative_to(root).as_posix(), line))
    counts = {severity: sum(m.group(2) == severity for m in findings) for severity in SEVERITIES}
    summary = section(text, '## Resumo')
    if summary is None:
        problem('summary', 'missing-summary-section')
    else:
        for severity in SEVERITIES:
            values = re.findall(r'\b' + severity + r':[ \t]*(\d+)\b', summary)
            if len(values) != 1 or int(values[0]) != counts[severity]:
                problem('summary', 'count-mismatch=' + severity)
    totals = re.findall(r'^Total:[ \t]*(\d+) achados[ \t]*$', text, re.MULTILINE)
    if len(totals) != 1 or int(totals[0]) != len(findings):
        problem('total', 'finding-count-mismatch')
    if section(text, '## Plano proposto e alterações de contrato') is None:
        problem('plan', 'missing-proposed-plan-section')
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[-1] != QUESTION:
        problem('confirmation', 'last-line-must-request-approval')
    return findings, counts, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--catalog', type=Path,
                        default=Path(__file__).resolve().parent.parent / 'references' / 'anti-patterns.md')
    parser.add_argument('report', help="arquivo do relatório ou '-' para ler da entrada padrão")
    args = parser.parse_args(argv)
    try:
        if args.report == '-':
            text = sys.stdin.buffer.read().decode('utf-8')
        else:
            text = Path(args.report).read_text(encoding='utf-8')
        catalog = args.catalog.read_text(encoding='utf-8')
        if not re.search(r'^### AP-\d{2,}\b', catalog, re.MULTILINE):
            raise ValueError('empty-catalog')
        if not args.project_root.is_dir():
            raise ValueError('invalid-root')
    except (OSError, ValueError, UnicodeError):
        print('PROBLEM input: unreadable-report-catalog-or-project')
        print('RESULT=failed PROBLEMS=1')
        return 2
    try:
        findings, counts, problems = validate(text, catalog, args.project_root.resolve())
    except (OSError, ValueError, UnicodeError):
        print('PROBLEM input: unreadable-project-source')
        print('RESULT=failed PROBLEMS=1')
        return 2
    if problems:
        for kind, detail in problems:
            print('PROBLEM {}: {}'.format(kind, detail))
        print('RESULT=failed PROBLEMS=' + str(len(problems)))
        return 1
    print('RESULT=ok FINDINGS={} {}'.format(len(findings), ' '.join(
        '{}={}'.format(severity, counts[severity]) for severity in SEVERITIES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
