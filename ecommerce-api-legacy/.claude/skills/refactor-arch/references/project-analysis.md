# Project analysis (knowledge area 1, Phase 1)

Phase 1 is read-only. Its output is the Phase 1 block printed at the top of the Phase 2 answer.

## 1. Mechanical inventory first

Run `python3 -I -B "$SKILL_DIR/scripts/inventory.py" --project-root "$PROJECT_ROOT"` and keep its output. It never
imports or executes the project. It prints:

- `LANGUAGE=`, `FRAMEWORK=`, `FILES=`, `LOC=`, `ENDPOINTS=`, `DATA_STORES=`, `DEPRECATIONS=` totals;
- `FILE <path> <lines>` for every source file it counted (dependency dirs, `.git`, skill dirs, `instance/` and build
  output excluded);
- `ENDPOINT <METHOD> <path> <file:line>` for every route (Flask decorators, blueprints and prefixes; Express
  `app`/`router` verbs and mounted prefixes);
- `TABLE <name> <file:line>` from `CREATE TABLE`, `__tablename__` and `db.Model` classes;
- `DEPENDENCY <name> declared=<spec> installed=<version>` for the direct dependencies declared in the manifests,
  with the installed version from metadata (`.venv/.../*.dist-info`, `node_modules/<pkg>/package.json`);
  transitive packages are not listed but their versions still drive the `DEPRECATED` status;
- `RUNTIME <python|node> <version|unknown>` (from `.venv/pyvenv.cfg`, `.python-version`, `engines`, ...);
- `ENTRY <file:line>` and `COMMAND <start|seed|install> <command>` from README and package.json;
- `DEPRECATED <rule> <file:line> status=<deprecated|version-unknown> severity=<...>`.

The numbers in the Phase 1 block (files, lines, endpoints) MUST be the inventory numbers. `check_report.py` compares
them. If you believe the inventory is wrong (a route it missed), say so in the Phase 2 "Cobertura" lines; do not
change the totals by hand.

`--summary` prints a pt-BR skeleton of the Phase 1 block with `Domínio` and `Arquitetura` left as "a analisar".

## 2. Reading code safely

Read source files only through the sanitized viewer:

```bash
python3 -I -B "$SKILL_DIR/scripts/safe_view.py" show --project-root "$PROJECT_ROOT" <relative/file> [--start N --end M]
```

It prints numbered lines and replaces secret-like literals with `<redacted>` while keeping keys, variable names and
interpolations visible. Use its line numbers in citations. Do not use `cat`, `sed`, `head`, `grep -n` or editors to
print source files that may contain credentials (config, app entry, models with seeds, utils). Listing files
(`ls`, `find -name`) and reading README/manifests is fine.

Never open the project's database files (`*.db`, `*.sqlite*`, `instance/`). Their schema is in the code.

## 3. Detection heuristics

Language: file extensions counted by the inventory; manifest type (`requirements.txt`/`pyproject.toml` -> Python,
`package.json` -> Node.js).

Framework and version: imports (`from flask import`, `require('express')`), app objects (`Flask(__name__)`,
`express()`), and the installed version from `DEPENDENCY ... installed=`. Prefer installed over declared versions;
say "declarada" when only a constraint exists.

Database: driver imports (`sqlite3`, `flask_sqlalchemy`, `sqlite3` npm package, `mongoose`, `pg`), connection strings
(`sqlite:///tasks.db`, `:memory:`), schema statements and models. Note the engine, where the file lives (relative
path) or "em memória", and the table names from `TABLE` lines.

Domain: infer from route prefixes, table names, model fields and README wording. Name it in pt-BR with the main
resources, e.g. "API de e-commerce (produtos, usuários, pedidos, relatórios)", "API de cursos (LMS) com checkout,
matrículas e pagamentos", "API de gerenciamento de tarefas (tarefas, usuários, categorias, relatórios)".

Architecture (current state): describe what exists, not the goal.
- Flat monolith: few files at the root, routes/handlers + SQL + rules mixed (e.g. `app.py`, `controllers.py`,
  `models.py`, `database.py` where "controllers" run SQL).
- God class: one class/file creating the DB, defining routes and holding the business rules.
- Partially layered: `models/`, `routes/`, `services/`, `utils/` exist, but check where the logic really is (routes
  with queries and rules = layers in name only).
Mention: entry point (`ENTRY`), how routes are registered (decorators, blueprints, router), where SQL lives, where
validation lives, configuration source (hardcoded vs environment), and the start/seed commands.

## 4. Phase 1 block (pt-BR, exact labels)

```text
================================
FASE 1: ANÁLISE DO PROJETO
================================
Linguagem:      <Python 3.14.4 | JavaScript (Node.js)>
Framework:      <Flask 3.1.1 | Express 4.22.1>
Dependências:   <direct dependencies with installed versions>
Domínio:        <domain in pt-BR with main resources>
Arquitetura:    <current architecture in one or two sentences>
Arquivos:       <FILES> arquivos de código, <LOC> linhas
Banco de dados: <engine> (<file path or "em memória">) — tabelas: <t1, t2, ...>
Endpoints:      <ENDPOINTS>
================================
```

Each label is followed by a non-empty value on the same line. `Arquivos:` starts with the inventory `FILES` number and
contains the `LOC` number; `Endpoints:` starts with the inventory `ENDPOINTS` number. You may add lines below
`Endpoints:` listing `METHOD /path` rows, but the totals stay the inventory totals.
