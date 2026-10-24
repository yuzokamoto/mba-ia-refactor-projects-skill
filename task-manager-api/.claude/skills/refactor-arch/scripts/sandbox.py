"""Execução de aplicações em cópias descartáveis com guarda do projeto original."""
import sys
sys.dont_write_bytecode = True

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

DEPENDENCIES = {'.venv', 'venv', 'node_modules'}
DATA_SKIP = DEPENDENCIES | {'.git'}
PROJECT_SKIP = DATA_SKIP | {'.worktrees'}
COPY_SKIP = {'.git', '.agents', '.claude', '__pycache__', '.pytest_cache',
             'reports', '.handoff', '.worktrees', 'instance'}
DATA_PATTERNS = ('*.db', '*.sqlite', '*.sqlite3', '*.db-journal', '*.db-wal', '*.db-shm')
NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')


def load_helper(name):
    """Carrega somente o auxiliar localizado junto deste script."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAFE_VIEW = load_helper('safe_view')


def inside(path, root):
    """Verifica contenção sem depender de métodos posteriores ao Python 3.9."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def walk(root, skip, skip_mounts=False):
    """Percorre entradas sem seguir diretórios simbólicos.

    Com skip_mounts, ignora pontos de montagem: sandboxes de agentes montam diretórios do ambiente
    (por exemplo .codex e .aws) dentro do projeto a cada comando, e eles não pertencem ao projeto.
    """
    def failed(error):
        raise error

    def mounted(directory, name):
        return skip_mounts and os.path.ismount(os.path.join(directory, name))
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        dirs[:] = sorted(name for name in dirs if name not in skip and not mounted(directory, name))
        files = [name for name in files if not mounted(directory, name)]
        for name in sorted(dirs + files):
            path = Path(directory) / name
            yield path, path.relative_to(root)


def is_data(relative):
    return 'instance' in relative.parts[:-1] or any(
        fnmatch.fnmatchcase(relative.name, pattern) for pattern in DATA_PATTERNS)


def fingerprints(project, strict=True):
    """Registra conteúdo e metadados dos armazenamentos, sem imprimi-los."""
    result = {}
    for path, relative in walk(project, DATA_SKIP):
        if is_data(relative) and not path.is_dir():
            try:
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('unsupported-data-store')
                digest = hashlib.sha256()
                with path.open('rb') as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b''):
                        digest.update(block)
                result[relative.as_posix()] = {'sha256': digest.hexdigest(), 'size': info.st_size,
                                               'mode': stat.S_IMODE(info.st_mode)}
            except (OSError, ValueError):
                if strict:
                    raise
                result[relative.as_posix()] = {'unreadable': True}
    return result


def snapshot(project):
    """Registra arquivos e diretórios sem ler conteúdo de código."""
    result = {}
    for path, relative in walk(project, PROJECT_SKIP, skip_mounts=True):
        info = path.lstat()
        result[relative.as_posix()] = [info.st_size, info.st_mtime_ns]
    return result


def save(root, state):
    """Atualiza o estado por substituição atômica."""
    path = root / 'state.json.new'
    path.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
    path.replace(root / 'state.json')


def load(root):
    """Recusa diretórios arbitrários e estados incompletos."""
    if root.is_symlink() or not root.name.startswith('refactor-arch-') or not root.is_dir():
        raise ValueError('invalid-run-root')
    root = root.resolve()
    state_path = root / 'state.json'
    if state_path.is_symlink():
        raise ValueError('invalid-state-link')
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if (not isinstance(state, dict) or state.get('version') != 1
            or not isinstance(state.get('project_root'), str)
            or not Path(state['project_root']).is_absolute()
            or not isinstance(state.get('data_stores'), dict)
            or not isinstance(state.get('groups'), list)
            or any(not isinstance(group, int) or group <= 1 or group == os.getpgrp()
                   for group in state['groups'])):
        raise ValueError('invalid-state')
    if inside(root, Path(state['project_root'])):
        raise ValueError('unsafe-run-root')
    return root, state


def guard(root, state):
    """Compara armazenamentos e a última fotografia do projeto."""
    project = Path(state['project_root'])
    problems = {tuple(item) for item in state.get('violations', [])}
    try:
        current = fingerprints(project, strict=False) if project.is_dir() else {}
    except OSError:
        current = dict(state['data_stores'])
        problems.add(('data_store_changed', '.'))
    for name, old in state['data_stores'].items():
        if name not in current:
            problems.add(('data_store_missing', name))
        elif old != current[name]:
            problems.add(('data_store_changed', name))
    for name in current.keys() - state['data_stores'].keys():
        problems.add(('data_store_new', name))
    if 'snapshot' in state:
        try:
            current_files = snapshot(project) if project.is_dir() else {}
        except OSError:
            current_files = dict(state['snapshot'])
            problems.add(('project_file_changed', '.'))
        for name in current_files.keys() - state['snapshot'].keys():
            problems.add(('project_file_added', name))
        for name, old in state['snapshot'].items():
            if current_files.get(name) != old:
                problems.add(('project_file_changed', name))
    state['violations'] = sorted(problems)
    save(root, state)
    print('DATA_GUARD=' + ('violation' if problems else 'ok'))
    for kind, name in sorted(problems):
        print('VIOLATION {} {}'.format(kind, name))
    return not problems


def initialize(project):
    """Cria a raiz privada apenas fora do projeto original."""
    project = project.resolve()
    temporary = Path(os.environ.get('TMPDIR') or '/tmp').resolve()
    if not project.is_dir() or not temporary.is_dir() or inside(temporary, project):
        raise ValueError('invalid-project-or-temp-root')
    stores = fingerprints(project)
    root = Path(tempfile.mkdtemp(prefix='refactor-arch-', dir=str(temporary)))
    try:
        root.chmod(0o700)
        for name in ('home', 'tmp', 'logs', 'copies'):
            (root / name).mkdir(mode=0o700)
        save(root, {'version': 1, 'project_root': str(project), 'data_stores': stores,
                    'groups': [], 'violations': []})
    except BaseException:
        shutil.rmtree(root)
        raise
    print('RUN_ROOT=' + str(root))
    print('DATA_STORES=' + str(len(stores)))
    for name in sorted(stores):
        print('DATA_STORE ' + name)
    return 0


def copy_path(root, name, existing=True):
    """Valida nome e contenção da cópia antes de qualquer execução."""
    if not NAME_RE.fullmatch(name):
        raise ValueError('invalid-copy-name')
    base = root / 'copies'
    if base.is_symlink() or not base.is_dir():
        raise ValueError('invalid-copies-root')
    path = base / name
    if path.is_symlink() or (existing and not path.is_dir()):
        raise ValueError('invalid-copy')
    return path


def excluded(relative):
    return (any(part in COPY_SKIP for part in relative.parts) or is_data(relative)
            or relative.name.endswith('.pyc')
            or relative.parts[0] in DEPENDENCIES)


def safe_member(name):
    """Recusa nomes absolutos e travessias em arquivos tar."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe-archive-member')
    return relative


def copy_tree(source, destination):
    """Copia arquivos regulares; links comuns não podem escapar da cópia."""
    count = 0
    for path, relative in walk(source, COPY_SKIP | DEPENDENCIES):
        if excluded(relative):
            continue
        target = destination / relative
        if path.is_symlink():
            link = Path(os.readlink(path))
            resolved = path.resolve()
            if link.is_absolute() or not inside(resolved, source):
                raise ValueError('unsafe-source-link')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
            count += 1
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            count += 1
        else:
            raise ValueError('unsupported-source-entry')
    return count


def copy_archive(project, destination, ref):
    """Extrai o commit com validação própria de nomes, tipos e links."""
    prefix = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-prefix'],
                            capture_output=True, check=True).stdout.decode().strip()
    if not ref or ref.startswith('-'):
        raise ValueError('invalid-ref')
    tree = ref + ':' + prefix.rstrip('/') if prefix else ref
    repository = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                                capture_output=True, check=True).stdout.decode().strip()
    count, links = 0, []
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(['git', '-C', repository, 'archive', '--format=tar', tree],
                                   stdout=subprocess.PIPE, stderr=errors)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                for member in archive:
                    relative = safe_member(member.name)
                    if not relative.parts or excluded(relative):
                        continue
                    target = destination / str(relative)
                    if not inside(target.parent.resolve(), destination):
                        raise ValueError('unsafe-archive-parent')
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, target.open('xb') as output:
                            shutil.copyfileobj(source, output)
                        target.chmod(member.mode & 0o777)
                        count += 1
                    elif member.issym() or member.islnk():
                        link = PurePosixPath(member.linkname)
                        anchor = target.parent if member.issym() else destination
                        if link.is_absolute() or not inside((anchor / str(link)).resolve(), destination):
                            raise ValueError('unsafe-archive-link')
                        links.append((target, member.linkname, member.issym()))
                    else:
                        raise ValueError('unsupported-archive-entry')
            if process.wait() != 0:
                raise ValueError('git-archive-failed')
            for target, name, symbolic in links:
                target.parent.mkdir(parents=True, exist_ok=True)
                anchor = target.parent if symbolic else destination
                if not inside((anchor / name).resolve(), destination):
                    raise ValueError('unsafe-archive-link')
                if symbolic:
                    target.symlink_to(name)
                else:
                    shutil.copy2(destination / name, target)
                count += 1
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()
    return count


def make_copy(root, state, args):
    destination = copy_path(root, args.name, existing=False)
    if destination.exists():
        raise ValueError('copy-exists')
    project = Path(state['project_root'])
    source = args.source.resolve() if args.source else project
    if not source.is_dir() or inside(destination, source) and source != project:
        raise ValueError('invalid-source')
    destination.mkdir(mode=0o700)
    try:
        count = (copy_archive(project, destination, args.ref) if args.ref
                 else copy_tree(source, destination))
        dependencies = project if args.ref else source
        for name in sorted(DEPENDENCIES):
            dependency = dependencies / name
            if dependency.is_dir():
                (destination / name).symlink_to(dependency.resolve(), target_is_directory=True)
    except BaseException:
        shutil.rmtree(destination)
        raise
    print('SOURCE=' + str(destination))
    print('FILES=' + str(count))
    return 0


class InputParser(argparse.ArgumentParser):
    """Não reproduz argumentos inválidos que possam conter segredos."""
    def error(self, message):
        self.exit(2, 'ERROR=invalid-arguments\n')


def environment(root, entries):
    """Valida pares e aplica sobrescritas explícitas após os padrões privados."""
    values = {}
    for entry in entries:
        key, separator, value = entry.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or '\x00' in value:
            raise ValueError('invalid-environment')
        values[key] = value
    result = dict(os.environ)
    result.update(HOME=str(root / 'home'), TMPDIR=str(root / 'tmp'), PYTHONDONTWRITEBYTECODE='1')
    result.update(values)
    return result, values


def timeout_value(value):
    """Aceita somente limites positivos e finitos."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('invalid-timeout')
    return number


def log_path(root, name, kind):
    """Reserva nomes sem sobrescrever registros anteriores."""
    directory = root / 'logs'
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('invalid-log-directory')
    index = 1
    while True:
        path = directory / '{}-{}-{}.log'.format(name, kind, index)
        try:
            handle = path.open('xb')
            return path, handle
        except FileExistsError:
            index += 1


def show_output(text, limit, values=None, omitted_key=None):
    """Oculta antes de truncar e mostra o final (onde ficam os resumos), inclusive valores do ambiente."""
    text = SAFE_VIEW.redact(text)
    for value in sorted((values or {}).values(), key=len, reverse=True):
        if value:
            text = text.replace(value, '<redacted>')
    lines = text.splitlines()
    if omitted_key and len(lines) > limit:
        print('{}={}'.format(omitted_key, len(lines) - limit))
    for line in lines[-limit:]:
        print(line)


def show_log(path, values):
    show_output(path.read_text(encoding='utf-8', errors='replace'), 40, values)


def start_process(command, cwd, env, output, root, state):
    """Inicia uma sessão e persiste o grupo para limpeza posterior."""
    process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                               stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        state['groups'].append(process.pid)
        save(root, state)
    except BaseException:
        signal_group(process.pid, signal.SIGKILL)
        process.wait()
        raise
    return process


def signal_group(group, sig):
    """Nunca sinaliza o grupo do próprio auxiliar ou identificadores reservados."""
    if not isinstance(group, int) or group <= 1 or group == os.getpgrp():
        raise ValueError('invalid-process-group')
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        pass


def stop_process(process, grace=5):
    """Encerra também descendentes cujo líder já terminou."""
    signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    finally:
        signal_group(process.pid, signal.SIGKILL)
        process.wait()


def prepare_snapshot(root, state):
    """Registra o estado imediatamente anterior à execução atual."""
    state['snapshot'] = snapshot(Path(state['project_root']))
    save(root, state)


def run_command(root, state, args, command):
    source = copy_path(root, args.name)
    env, values = environment(root, args.env)
    timeout = timeout_value(args.timeout)
    if not command:
        raise ValueError('missing-command')
    path, handle = log_path(root, args.name, 'run')
    prepare_snapshot(root, state)
    process, code = None, 127
    try:
        with handle:
            try:
                process = start_process(command, source, env, handle, root, state)
            except OSError:
                handle.write(b'PROCESS_START=failed\n')
            if process is not None:
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    print('TIMEOUT=yes')
                    signal_group(process.pid, signal.SIGKILL)
                    code = process.wait()
    except BaseException:
        if process is not None:
            stop_process(process, grace=0)
        guard(root, state)
        raise
    show_log(path, values)
    print('EXIT=' + str(code))
    print('LOG=' + str(path))
    print('ENV_KEYS=' + ','.join(sorted(values)))
    ok = guard(root, state)
    return 0 if code == 0 and ok else 1


def port_open(port):
    """Consulta somente a interface local e com espera limitada."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.1):
            return True
    except OSError:
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Trata redirecionamentos como respostas, sem sair do servidor local."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_ready(base, path, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(base + path, timeout=timeout):
            return True
    except urllib.error.HTTPError as error:
        error.close()
        return True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def client_command(root, state, command, values, base):
    """Executa o cliente no diretório e ambiente originais do chamador."""
    env = dict(os.environ, BASE_URL=base)
    with tempfile.TemporaryFile(dir=str(root / 'tmp')) as output:
        try:
            process = start_process(command, Path.cwd(), env, output, root, state)
        except OSError:
            print('CLIENT_START=failed')
            return 127
        try:
            code = process.wait()
        except BaseException:
            stop_process(process, grace=0)
            raise
        output.seek(0)
        show_output(output.read().decode('utf-8', errors='replace'), 200, values, 'CLIENT_OMITTED_LINES')
        return code


def serve_command(root, state, args, command):
    """Aguarda prontidão, executa o cliente e garante a parada do servidor."""
    source = copy_path(root, args.name)
    env, values = environment(root, args.env)
    timeout = timeout_value(args.timeout)
    try:
        split = next(i for i in range(len(command) - 1)
                     if command[i:i + 2] == ['--then', '--'])
    except StopIteration:
        raise ValueError('missing-client-separator') from None
    server, client = command[:split], command[split + 2:]
    if not server or not client or not 1 <= args.port <= 65535:
        raise ValueError('invalid-server-client-or-port')
    if args.ready is not None and (not args.ready.startswith('/') or args.ready.startswith('//')
                                   or any(c in args.ready for c in '\r\n')):
        raise ValueError('invalid-ready-path')
    if port_open(args.port):
        print('PORT_BUSY=' + str(args.port))
        return 1
    base = 'http://127.0.0.1:' + str(args.port)
    path, handle = log_path(root, args.name, 'serve')
    process, ready, client_exit = None, False, 127
    prepare_snapshot(root, state)
    try:
        with handle:
            try:
                process = start_process(server, source, env, handle, root, state)
            except OSError:
                handle.write(b'PROCESS_START=failed\n')
            if process is not None:
                deadline = time.monotonic() + timeout
                while process.poll() is None and time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    if port_open(args.port) and (args.ready is None or http_ready(
                            base, args.ready, max(0.001, min(0.2, remaining)))):
                        ready = process.poll() is None
                        break
                    time.sleep(min(0.03, max(0, deadline - time.monotonic())))
            print('SERVER_READY=' + ('yes' if ready else 'no'))
            if ready:
                client_exit = client_command(root, state, client, values, base)
                print('CLIENT_EXIT=' + str(client_exit))
    finally:
        if process is not None:
            stop_process(process)
        deadline = time.monotonic() + 1
        while port_open(args.port) and time.monotonic() < deadline:
            time.sleep(0.03)
        free = not port_open(args.port)
        if not ready:
            show_log(path, values)
        print('PORT_FREE=' + ('yes' if free else 'no'))
        print('SERVER_LOG=' + str(path))
        print('ENV_KEYS=' + ','.join(sorted(values)))
        ok = guard(root, state)
    return 0 if ready and client_exit == 0 and free and ok else 1


def syntax_check(root, args):
    """Verifica sintaxe sem gerar bytecode ou executar módulos do projeto."""
    source = copy_path(root, args.name)
    node = shutil.which('node')
    if node is None:
        print('NODE=missing')
    failures, count = 0, 0
    env, _ = environment(root, [])
    for path, relative in walk(source, DEPENDENCIES):
        if not path.is_file() or path.suffix not in ('.py', '.js', '.mjs', '.cjs'):
            continue
        if not inside(path.resolve(), source):
            raise ValueError('syntax-path-outside-copy')
        count += 1
        line = None
        if path.suffix == '.py':
            try:
                compile(path.read_bytes(), str(path), 'exec')
            except SyntaxError as error:
                line = error.lineno or 1
        elif node:
            result = subprocess.run([node, '--check', str(path)], cwd=str(source), env=env,
                                    capture_output=True, timeout=30)
            if result.returncode:
                text = result.stderr.decode('utf-8', errors='replace')
                match = re.search(re.escape(str(path)) + r':(\d+)', text)
                line = int(match.group(1)) if match else 1
        if line is not None:
            failures += 1
            print('SYNTAX_ERROR {}:{}'.format(relative.as_posix(), line))
    print('SYNTAX={} FILES={}'.format('failed' if failures else 'ok', count))
    return 1 if failures else 0


def finish_run(root, state):
    """Mata grupos persistidos e remove a raiz mesmo diante de violação."""
    for group in state['groups']:
        signal_group(group, signal.SIGKILL)
    ok = guard(root, state)
    shutil.rmtree(root)
    print('FINISH=' + ('ok' if ok else 'failed'))
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    execution = []
    if argv and argv[0] in ('run', 'serve') and '--' in argv:
        index = argv.index('--')
        execution, argv = argv[index + 1:], argv[:index]
    parser = InputParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--project-root', type=Path, required=True)
    for name in ('copy', 'check', 'finish', 'run', 'serve', 'syntax'):
        command = commands.add_parser(name)
        command.add_argument('--run-root', type=Path, required=True)
        if name == 'copy':
            command.add_argument('--name', required=True)
            source = command.add_mutually_exclusive_group()
            source.add_argument('--from', dest='source', type=Path)
            source.add_argument('--ref')
        if name in ('run', 'serve', 'syntax'):
            command.add_argument('--name', required=True)
        if name in ('run', 'serve'):
            command.add_argument('--env', action='append', default=[])
            command.add_argument('--timeout', default='30' if name == 'serve' else '120')
        if name == 'serve':
            command.add_argument('--port', type=int, required=True)
            command.add_argument('--ready')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            return initialize(args.project_root)
        root, state = load(args.run_root)
        if args.command == 'copy':
            return make_copy(root, state, args)
        if args.command == 'check':
            return 0 if guard(root, state) else 1
        if args.command == 'run':
            return run_command(root, state, args, execution)
        if args.command == 'serve':
            return serve_command(root, state, args, execution)
        if args.command == 'syntax':
            return syntax_check(root, args)
        if args.command == 'finish':
            return finish_run(root, state)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError):
        print('ERROR=invalid-input-or-unreadable-path', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
