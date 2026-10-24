"""Leitura de código com ocultação de valores sensíveis e sem execução."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import difflib
import os
from pathlib import Path
import re
import subprocess

SECRET_NAME = (r'(?:password|passwd|senha|secret|token|api[_-]?key|private|'
               r'credential|smtp[_-]?pass|card|cart[aã]o|(?:\b|_)key(?:\b|_))')
SECRET_RE = re.compile(SECRET_NAME, re.IGNORECASE)
# Segmentos (snake, kebab ou camelCase) que tornam um nome sensível.
SECRET_SEGMENTS = {'pass', 'passwd', 'password', 'passwords', 'pwd', 'senha', 'senhas', 'secret',
                   'secrets', 'token', 'tokens', 'key', 'apikey', 'credential', 'credentials', 'private',
                   'card', 'cardnumber', 'cartao', 'cartão', 'cvv', 'cvc', 'salt', 'pin'}
SECRET_SUBSTRINGS = ('password', 'passwd', 'senha', 'secret', 'credential', 'apikey', 'privatekey', 'token')
HASH_SEGMENT_RE = re.compile(r'(?:md5|sha\d*|hash\w*|\w*crypt\w*|cipher\w*|hmac\w*|bcrypt|scrypt|pbkdf2\w*)\Z')
# Literais que nunca são segredo e que o agente precisa ver (algoritmos e codificações).
KEEP_LITERALS = {'md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512', 'hex', 'base64', 'utf-8', 'utf8',
                 'ascii', 'latin1', 'latin-1', 'binary', 'aes-256-cbc', 'aes-256-gcm', 'aes-128-cbc',
                 'pbkdf2:sha256', 'scrypt', 'bcrypt'}
LOOKUP_CALLS = {'get', 'getenv', 'pop', 'setdefault', 'getattr', 'hasattr', 'environ', 'get_json', 'getlist',
                'header', 'param', 'cookie', 'cookies'}
STRING_RE = re.compile(
    r'''(?P<prefix>(?i:[rubf]{0,2}))(?P<quote>\x22{3}|'{3}|[\x22'`])'''
    r'''(?P<body>(?:\\[\s\S]|(?!(?P=quote))[\s\S])*?)(?P=quote)''')
TOKEN_RE = re.compile(r'#[^\r\n]*|//[^\r\n]*|/\*[\s\S]*?\*/|' + STRING_RE.pattern)
KEY_ASSIGN_RE = re.compile(
    r'''(?<![\w])["']?([\w-]+)["']?\s*\]?\s*(?::\s*[\w.\[\]]+\s*)?(?::|=(?![=>]))\s*''')
COMPARE_RE = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:===|!==|==|!=)\s*')
CALL_RE = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*)\s*\(')
URL_RE = re.compile(r'''(?<=://)[^\s/"'`@]+:[^\s/"'`@]+@''')
DIGITS_RE = re.compile(r'(?<!\d)\d{12,19}(?!\d)')
PEM_RE = re.compile(r'-----BEGIN ([A-Z0-9 ]+)-----[\s\S]*?(?:-----END \1-----|\Z)')

IDENTIFIER_RE = re.compile(r'[A-Za-z_][\w.-]{0,63}\Z')
# SQL: colunas sensíveis em INSERT/UPDATE recebem valores literais ou linhas posicionais de seed.
SQL_INSERT_RE = re.compile(r'\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."`\[\]]+\s*\(([^()]*)\)\s*VALUES\s*',
                           re.IGNORECASE)
SQL_ASSIGN_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*=\s*'((?:[^']|'')*)'")
SQL_KEYWORD_RE = re.compile(r'\b(?:SELECT|INSERT|UPDATE|DELETE|WHERE)\b', re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r'\?|%s|%\(\w+\)s|[:@$]\w+')
ROW_LITERAL_RE = re.compile(r'-?\d+(?:\.\d+)?|None|null|undefined|True|False|true|false')


def masked_body(value):
    """Preserva as quebras para manter a numeração original."""
    return '<redacted>' + ''.join(re.findall(r'\r\n|\r|\n', value))


def name_segments(name):
    """Divide snake_case, kebab-case e camelCase em segmentos minúsculos."""
    spaced = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    spaced = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', spaced)
    return [part for part in re.split(r'[^0-9a-zà-ÿ]+', spaced.lower()) if part]


def is_secret_name(name):
    """Nome de variável, chave ou parâmetro que guarda segredo."""
    segments = name_segments(name)
    joined = ''.join(segments)
    return any(part in SECRET_SEGMENTS for part in segments) or any(word in joined for word in SECRET_SUBSTRINGS)


def is_sensitive_call(name):
    """Funções de senha, segredo ou hash: seus argumentos literais ficam ocultos."""
    lowered = name.lower()
    return (is_secret_name(name) or 'crypt' in lowered or 'hash' in lowered
            or any(HASH_SEGMENT_RE.match(part) for part in name_segments(name)))


def _value_end(text, index, starts):
    """Avança até o fim da expressão (vírgula, ponto e vírgula, quebra ou fecha-parênteses)."""
    begin, depth = index, 0
    while index < len(text):
        if index in starts:
            index = starts[index]
            continue
        char = text[index]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and char in ',;':
            break
        elif depth == 0 and char in '\r\n':
            previous = text[begin:index].rstrip()
            if not previous or previous[-1] not in '\\|+?=:&':
                break
        index += 1
    return index


def _closing_paren(text, index, starts):
    """Posição do parêntese que fecha a chamada aberta em index-1."""
    depth = 0
    while index < len(text):
        if index in starts:
            index = starts[index]
            continue
        char = text[index]
        if char in '([{':
            depth += 1
        elif char in ')]}':
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return index


def _inside_token(tokens, position):
    return next((token for token in tokens if token.start() <= position < token.end()), None)


def secret_value_ranges(text):
    """Delimita expressões sensíveis: atribuições, comparações e argumentos de chamadas sensíveis.

    Retorna tuplas (início, fim, modo); modo 'value' para valores de nomes sensíveis e 'call' para
    argumentos de funções de senha/hash.
    """
    tokens = list(TOKEN_RE.finditer(text))
    starts = {token.start(): token.end() for token in tokens}
    ranges = []
    for regex in (KEY_ASSIGN_RE, COMPARE_RE):
        for assignment in regex.finditer(text):
            if not is_secret_name(assignment.group(1)):
                continue
            covering = _inside_token(tokens, assignment.start())
            if covering and (covering.group('quote') is None or covering.start() != assignment.start()):
                continue
            ranges.append((assignment.end(), _value_end(text, assignment.end(), starts), 'value'))
    for call in CALL_RE.finditer(text):
        if not is_sensitive_call(call.group(1)) or _inside_token(tokens, call.start()):
            continue
        ranges.append((call.end(), _closing_paren(text, call.end(), starts), 'call'))
    return ranges


def _previous_char(text, position):
    index = position - 1
    while index >= 0 and text[index] in ' \t':
        index -= 1
    return text[index] if index >= 0 else '\n'


def _next_char(text, position):
    index = position
    while index < len(text) and text[index] in ' \t':
        index += 1
    return text[index] if index < len(text) else '\n'


def _structural(text, match):
    """Literais que mostram estrutura (chaves, nomes de env, módulos) continuam visíveis."""
    body = match.group('body')
    # Nomes de env só ficam visíveis em contexto de lookup/subscript/chave (abaixo): um literal
    # UPPER_SNAKE solto pode ser o próprio segredo.
    if not body or body.lower() in KEEP_LITERALS:
        return True
    before, after = _previous_char(text, match.start()), _next_char(text, match.end())
    if after == ':' and before in '{,\n\r(':
        return True
    if before == '[' and after == ']':
        return True
    prefix = text[max(0, match.start() - 40):match.start()]
    if re.search(r'(?:\brequire|\bimport)\s*\(\s*\Z|\bfrom\s+\Z', prefix):
        return True
    lookup = re.search(r'(?<![\w$])([A-Za-z_$][\w$]*)\s*\(\s*\Z', prefix)
    if lookup and lookup.group(1) in LOOKUP_CALLS and IDENTIFIER_RE.match(body):
        return True
    return False


def _sql_items(body, index):
    """Itens de uma tupla SQL que abre em index: lista de (início, fim) e posição após o ')'."""
    items, start, depth, position = [], index + 1, 0, index + 1
    while position < len(body):
        char = body[position]
        if char == "'":
            position += 1
            while position < len(body):
                if body[position] == "'" and body[position + 1:position + 2] == "'":
                    position += 2
                    continue
                if body[position] == "'":
                    break
                position += 1
        elif char == '(':
            depth += 1
        elif char == ')' and depth:
            depth -= 1
        elif char in ',)' and not depth:
            items.append((start, position))
            if char == ')':
                return items, position + 1
            start = position + 1
        position += 1
    return items, position


def _sql_inserts(body):
    """Para cada INSERT do texto: (índices das colunas sensíveis, tuplas de itens de VALUES)."""
    for match in SQL_INSERT_RE.finditer(body):
        columns = [column.strip().strip('"`[]') for column in match.group(1).split(',')]
        secret = {index for index, column in enumerate(columns) if is_secret_name(column)}
        rows, position = [], match.end()
        while position < len(body) and body[position] == '(':
            items, position = _sql_items(body, position)
            rows.append(items)
            rest = re.match(r'\s*,\s*', body[position:])
            if not rest:
                break
            position += rest.end()
        yield len(columns), secret, rows


def sql_secret_spans(body):
    """Trechos (início, fim) do corpo de um literal SQL que guardam valores de colunas sensíveis."""
    if not SQL_KEYWORD_RE.search(body):
        return []
    spans = []
    for _, secret, rows in _sql_inserts(body):
        for items in rows:
            for index in secret:
                if index < len(items):
                    start, end = items[index]
                    value = body[start:end].strip()
                    if len(value) >= 2 and value[0] == value[-1] == "'":
                        offset = body.index("'", start)
                        spans.append((offset + 1, offset + len(value) - 1))
    for match in SQL_ASSIGN_RE.finditer(body):
        if is_secret_name(match.group(1)):
            spans.append(match.span(2))
    return sorted(set(spans))


def secret_row_literals(text, tokens):
    """Literais de linhas posicionais (tuplas/listas só de literais) ligadas a um INSERT com placeholders.

    Ex.: ("Ana", "ana@x", "<senha>", "admin") com "INSERT INTO usuarios (nome, email, senha, tipo)
    VALUES (?, ?, ?, ?)" no mesmo arquivo: o 3º item é oculto. Retorna as posições iniciais dos literais.
    """
    arities = {}
    for token in tokens:
        if token.group('quote') is None:
            continue
        for arity, secret, rows in _sql_inserts(token.group('body')):
            body = token.group('body')
            placeholders = rows and all(PLACEHOLDER_RE.fullmatch(body[start:end].strip())
                                        for items in rows for start, end in items)
            if secret and placeholders:
                arities.setdefault(arity, set()).update(secret)
    if not arities:
        return set()
    by_start = {token.start(): token for token in tokens}
    spans = [(token.start(), token.end()) for token in tokens]
    hidden = set()
    for opening in re.finditer(r'[(\[]', text):
        position = opening.start()
        if any(start <= position < end for start, end in spans):
            continue
        before = _previous_char(text, position)
        if before.isalnum() or before in '_$)].':
            continue
        closing = ')' if opening.group() == '(' else ']'
        items, index, valid = [], position + 1, False
        while index < len(text):
            while index < len(text) and text[index] in ' \t\r\n':
                index += 1
            if index < len(text) and text[index] == closing:
                valid = bool(items)
                break
            token = by_start.get(index)
            if token is not None and token.group('quote') is not None:
                items.append(token)
                index = token.end()
            else:
                literal = ROW_LITERAL_RE.match(text, index)
                if not literal:
                    break
                items.append(None)
                index = literal.end()
            while index < len(text) and text[index] in ' \t\r\n':
                index += 1
            if index < len(text) and text[index] == ',':
                index += 1
            elif index < len(text) and text[index] == closing:
                valid = True
                break
            else:
                break
        if valid and len(items) in arities:
            hidden.update(items[i].start() for i in arities[len(items)] if items[i] is not None)
    return hidden


def _interpolated(match):
    body, prefix = match.group('body'), match.group('prefix').lower()
    return (match.group('quote') == '`' and '${' in body) or ('f' in prefix and '{' in body)


def hidden_literals(text):
    """Lista (match, modo) dos literais que o visualizador oculta; modo 'full' ou 'static'."""
    ranges = secret_value_ranges(text)
    tokens = list(TOKEN_RE.finditer(text))
    rows = secret_row_literals(text, tokens)
    hidden = []
    for match in tokens:
        if match.group('quote') is None:
            continue
        if match.start() in rows:
            hidden.append((match, 'full'))
            continue
        modes = [mode for start, end, mode in ranges if start <= match.start() < end]
        if modes and not _structural(text, match):
            if not _interpolated(match):
                hidden.append((match, 'full'))
                continue
            if 'value' in modes:
                hidden.append((match, 'static'))
                continue
        spans = sql_secret_spans(match.group('body'))
        if spans:
            hidden.append((match, ('sql', spans)))
    return hidden


def _sql_redacted(match, spans):
    """Oculta só os valores das colunas sensíveis dentro do SQL."""
    body, parts, last = match.group('body'), [], 0
    for start, end in spans:
        parts.append(body[last:start])
        parts.append(masked_body(body[start:end]))
        last = end
    return ''.join(parts) + body[last:]


def _static_redacted(match):
    """Oculta o texto fixo de templates e mantém as interpolações visíveis."""
    body = match.group('body')
    if match.group('quote') == '`':
        parts = re.split(r'(\$\{[^}]*\})', body)
    else:
        parts = re.split(r'(\{[^{}]*\})', body)
    return ''.join(part if part.startswith(('${', '{')) else ('<redacted>' if part.strip() else part)
                   for part in parts)


def redact(text):
    """Oculta valores sensíveis; preserva os demais caracteres e linhas."""
    text = PEM_RE.sub(lambda m: masked_body(m.group()), text)
    hidden = {match.start(): mode for match, mode in hidden_literals(text)}

    def replace(match):
        mode = hidden.get(match.start()) if match.group('quote') is not None else None
        if mode == 'full':
            return (match.group('prefix') + match.group('quote') +
                    masked_body(match.group('body')) + match.group('quote'))
        if mode == 'static':
            return match.group('prefix') + match.group('quote') + _static_redacted(match) + match.group('quote')
        if isinstance(mode, tuple):
            return match.group('prefix') + match.group('quote') + _sql_redacted(match, mode[1]) + match.group('quote')
        return match.group()

    text = TOKEN_RE.sub(replace, text)
    text = URL_RE.sub('<redacted>@', text)
    return DIGITS_RE.sub('<redacted>', text)


def sensitive_literals(text):
    """Coleta exatamente os valores que redact() oculta, sem nunca imprimi-los."""
    for match, mode in hidden_literals(text):
        line = text.count('\n', 0, match.start()) + 1
        if isinstance(mode, tuple):
            pieces = [match.group('body')[start:end].replace("''", "'") for start, end in mode[1]]
        elif mode == 'static':
            pieces = re.split(r'\$\{[^}]*\}|\{[^{}]*\}', match.group('body'))
        else:
            try:
                value = ast.literal_eval(match.group())
            except (ValueError, SyntaxError):
                value = match.group('body')
            if isinstance(value, bytes):
                value = value.decode('utf-8', errors='replace')
            pieces = [value, match.group('body'), *value.splitlines()] if isinstance(value, str) else []
        for candidate in set(pieces):
            if len(candidate.strip()) >= 6:
                yield candidate, line
    for regex in (URL_RE, DIGITS_RE):
        for match in regex.finditer(text):
            value = match.group().rstrip('@')
            if len(value) >= 6:
                yield value, text.count('\n', 0, match.start()) + 1


def checked_path(root, name):
    """Resolve caminhos e recusa escapes, inclusive por links simbólicos."""
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('path-outside-project') from None
    return path


def git(root, *args, optional=False):
    """Lê o repositório sem atualizar o índice ou acionar programas externos."""
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_PAGER='cat')
    result = subprocess.run(['git', '--no-pager', '--literal-pathspecs', '-C', str(root),
                             *args], capture_output=True, env=environment)
    if result.returncode and not optional:
        raise ValueError('git-read-failed')
    return result.stdout if not result.returncode else None


def safe_diff(root, names):
    """Compara HEAD e disco, ignorando o estado intermediário do índice."""
    filters = [checked_path(root, name).relative_to(root).as_posix() for name in names]
    repository = Path(os.fsdecode(git(root, 'rev-parse', '--show-toplevel')).strip()).resolve()
    base = root.relative_to(repository).as_posix()
    prefix = '' if base == '.' else base + '/'
    tracked = git(root, 'ls-tree', '-r', '--name-only', '-z', 'HEAD', optional=True) or b''
    current = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
    paths = {os.fsdecode(item) for item in (tracked + current).split(b'\0') if item}
    output = []
    for name in sorted(paths):
        if filters and not any(name == item or name.startswith(item.rstrip('/') + '/') or item == '.'
                               for item in filters):
            continue
        path = checked_path(root, name)
        old = git(root, 'show', 'HEAD:' + prefix + name, optional=True)
        new = path.read_bytes() if path.is_file() else None
        if old == new:
            continue
        if b'\0' in (old or b'') or b'\0' in (new or b''):
            output.append('BINARY ' + name + '\n')
            continue
        before = redact((old or b'').decode('utf-8')).splitlines(keepends=True)
        after = redact((new or b'').decode('utf-8')).splitlines(keepends=True)
        if not before and not after:
            output.append('--- {}\n+++ {}\n'.format(
                'a/' + name if old is not None else '/dev/null',
                'b/' + name if new is not None else '/dev/null'))
            continue
        diff = difflib.unified_diff(before, after,
                                    fromfile='a/' + name if old is not None else '/dev/null',
                                    tofile='b/' + name if new is not None else '/dev/null')
        for line in diff:
            output.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
    return ''.join(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    show = commands.add_parser('show')
    show.add_argument('--project-root', type=Path, required=True)
    show.add_argument('file')
    show.add_argument('--start', type=int, default=1)
    show.add_argument('--end', type=int)
    diff = commands.add_parser('diff')
    diff.add_argument('--project-root', type=Path, required=True)
    diff.add_argument('paths', nargs='*')
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    try:
        if args.command == 'diff':
            sys.stdout.write(safe_diff(root, args.paths))
            return 0
        if args.start < 1 or (args.end is not None and args.end < args.start):
            raise ValueError('invalid-range')
        path = checked_path(root, args.file)
        with path.open(encoding='utf-8', newline='') as handle:
            lines = redact(handle.read()).splitlines(keepends=True)
        for index, line in enumerate(lines, 1):
            if index >= args.start and (args.end is None or index <= args.end):
                sys.stdout.write('{}: {}'.format(index, line))
    except (OSError, ValueError):
        print('ERROR=invalid-path-or-range', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
