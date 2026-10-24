# Anti-pattern catalog (knowledge area 2)

Use this catalog in Phase 2. Every finding in the report cites one or more ids from this file, e.g.
`(AP-02)` or `(AP-07/AP-11)`. `scripts/check_report.py` reads the `## <SEVERITY>` sections and `### AP-NN`
headings below, so do not rename them.

Rules for using the catalog:

- A finding is a CONFIRMED problem: you read the cited lines (with `scripts/safe_view.py show`) and they contain the
  signal. Checks you could not confirm are not findings; mention them in the "Cobertura" line of the plan section
  instead. Never write "não confirmado", "sem evidência" or similar inside a finding.
- One root cause = one finding. Group every location of the same root cause in one finding (`Arquivo:` accepts several
  `path:line[-line]` items separated by `;`). An AP id appears in at most one finding.
- Severity: use the default severity of the section where the AP lives. You may move one level up or down when the
  "Severity" note of the AP says so (for example an unauthenticated endpoint that only reads public data). A finding
  that groups several APs takes the most severe one.
- Cite exact lines. A range must cover the code that shows the problem, not the whole file, unless the problem is the
  whole file (God module).
- Secret values are never copied into the report. Cite `path:line` and the name of the variable or key. In
  `safe_view.py` output, `NAME = "<redacted>"` on a secret-like name IS the evidence of a hardcoded credential, and an
  interpolation such as `${card}` or `{password}` inside a log or response IS the evidence of sensitive data exposure.
- Deprecated APIs: `scripts/inventory.py` prints `DEPRECATED <rule> file:line status=...`. `status=deprecated` is
  confirmed by the installed/declared versions it printed; report it under AP-16. `status=version-unknown` must be
  checked against the versions shown in Phase 1 before you report it.

Each entry: signals (what to look for), severity notes, and the playbook transformation that fixes it
(`references/refactoring-playbook.md`, ids `P-NN`).

## CRITICAL

### AP-01 Hardcoded credentials and secrets
Report title (pt-BR): "Credenciais e segredos hardcoded".
Signals:
- Assignments of string literals to names or keys containing `secret`, `password`, `passwd`, `senha`, `token`,
  `api_key`, `apikey`, `key`, `credential`, `private`: `SECRET_KEY = "..."`, `app.config["SECRET_KEY"] = "..."`,
  `const DB_PASS = '...'`, `smtp_password = "..."`, payment gateway keys, JWT secrets.
- Connection strings with user:password (`postgres://user:pass@host`).
- Default values of `os.getenv("X", "<literal>")` / `process.env.X || '<literal>'` for secrets: the literal is the
  real value in every environment without the variable.
Severity: CRITICAL. Keep CRITICAL even for "dev" secrets: they ship with the code.
Fix: P-01.

### AP-02 SQL injection
Report title: "SQL Injection".
Signals:
- SQL text built with `+`, `%`, `.format(`, f-strings or template literals that include request data or function
  parameters: `"SELECT ... WHERE email = '" + email + "'"`, `` `... WHERE id = ${id}` ``.
- `cursor.execute(query)` / `db.run(sql)` / `db.all(sql)` where `query` was assembled from variables on earlier lines.
- Endpoints that execute arbitrary SQL received from the client (`/admin/query`).
Severity: CRITICAL.
Fix: P-02 (and P-05 for endpoints that run client-supplied SQL).

### AP-03 Missing authentication or authorization on sensitive operations
Report title: "Endpoints sensíveis sem autenticação/autorização".
Signals:
- Admin, destructive or financial routes with no auth check: `/admin/*`, `reset-db`, `DELETE /users/:id`, reports
  with revenue, bulk updates.
- Role or privilege taken from the request body (`role = data.get('role')`) without checking the caller.
- Tokens that are predictable (`'token-' + str(user.id)`, base64 of the id, timestamps) or never verified.
- Login endpoints that return a token that no other route checks.
Severity: CRITICAL for destructive/admin/financial/role-escalation; HIGH when the unprotected route only reads
non-sensitive data.
Fix: P-05.

### AP-04 Sensitive data exposure
Report title: "Exposição de dados sensíveis".
Signals:
- Serializers (`to_dict`, `toJSON`, row-to-dict helpers, `SELECT *` returned as is) that include `password`, `senha`,
  `password_hash`, `hash`, `salt`, tokens or secrets in API responses.
- Health/debug endpoints returning configuration values (`secret_key`, DB paths with credentials, env dumps).
- Logs (`print`, `console.log`, `logger.*`) with card numbers, CVV, passwords, tokens or gateway keys.
- Error responses that include stack traces or raw exception text (see AP-14 for the error-handling part).
Severity: CRITICAL when passwords, hashes, card data or secrets leave the process; HIGH for personal data only.
Fix: P-04.

### AP-05 Plaintext or weak password storage
Report title: "Senhas em texto puro ou com hash fraco".
Signals:
- Passwords stored or compared as plain text (`WHERE senha = ?` with the raw input, `user.password == data['password']`).
- `md5`, `sha1`, unsalted `sha256` of passwords, homemade "crypto" (base64, XOR, reversed strings, fixed salt).
- Default passwords assigned in code when the client omits one.
Severity: CRITICAL for plaintext and reversible encodings; HIGH for unsalted fast hashes (MD5/SHA1).
Fix: P-03.

### AP-06 God class / God module
Report title: "God Class / God Module".
Signals:
- One class or file that does routing/HTTP handling AND SQL/persistence AND business rules for several domains
  (`AppManager` with `app.get(...)`, `db.run(...)` and checkout rules; `models.py` with queries + validation +
  formatting for 4 entities).
- More than ~300 lines spanning 3+ resources, or a constructor that creates the DB, the schema and the routes.
Severity: CRITICAL when HTTP + persistence + rules live together; HIGH when only rules + persistence are mixed.
Fix: P-06, P-07.

## HIGH

### AP-07 Business logic and persistence inside route handlers (fat controllers)
Report title: "Regra de negócio e persistência nas rotas".
Signals:
- Route functions longer than ~15 lines that query the DB (`db.session`, `Model.query`, `cursor.execute`,
  `db.run`), apply business rules (status transitions, stock, totals, permissions) and build responses.
- The same rule implemented in several handlers.
- Handlers that commit transactions directly.
Severity: HIGH. CRITICAL only if it is the God-module case (use AP-06 instead).
Fix: P-07.

### AP-08 Global mutable state and shared connections
Report title: "Estado global mutável / conexão compartilhada".
Signals:
- Module-level DB connection or cursor reused by every request (`conn = sqlite3.connect(..., check_same_thread=False)`
  at import time; a single `db` object mutated across requests without lifecycle).
- Module-level dicts/lists used as caches, counters or sessions that requests mutate.
- `global` statements in request paths.
Severity: HIGH.
Fix: P-08.

### AP-09 Non-atomic multi-step writes
Report title: "Operações de escrita sem transação".
Signals:
- Order/checkout flows that insert several rows and update stock/balances with separate commits or callbacks and no
  rollback on failure.
- Stock checked in one loop and decremented in another without a transaction.
- Nested callbacks (`db.run` inside `db.run`) with errors ignored.
Severity: HIGH (data corruption under failure); MEDIUM when the steps are idempotent.
Fix: P-09.

### AP-10 Insecure runtime configuration
Report title: "Configuração insegura de execução".
Signals:
- `debug=True` / `app.debug = True` / dev error pages enabled by default.
- Binding `0.0.0.0` by default in code.
- CORS open to every origin (`CORS(app)` without origins, `origin: '*'`) on an API with credentials or admin routes.
- Secrets or debug flags read from code instead of the environment (combine with AP-01 when the value is a secret).
Severity: HIGH for debug mode with interactive debugger or binding all interfaces; MEDIUM for wildcard CORS alone.
Fix: P-01 (config module), P-12.

### AP-11 Tight coupling without dependency injection
Report title: "Acoplamento forte sem injeção de dependência".
Signals:
- Handlers or services that instantiate their own DB connections, gateways or services (`sqlite3.connect` inside
  functions, `new PaymentService()` per request) instead of receiving them.
- Import-time side effects: creating tables, seeding data or opening connections when a module is imported.
- Circular imports worked around with imports inside functions.
Severity: HIGH when it blocks testing in isolation; MEDIUM otherwise.
Fix: P-15.

## MEDIUM

### AP-12 N+1 queries
Report title: "Queries N+1".
Signals:
- A query inside a `for` loop over the result of another query (`for order in orders: cursor.execute(... order.id)`,
  `task.user` lazy load per item, `db.get` inside `forEach`).
- Counting or summing in Python/JS by loading all rows and looping when SQL `COUNT/SUM/GROUP BY` would do.
Severity: MEDIUM; HIGH if the loop is unbounded on a hot endpoint.
Fix: P-10.

### AP-13 Missing or inconsistent input validation
Report title: "Validação de entrada ausente ou inconsistente".
Signals:
- `request.get_json()` / `req.body` fields used without type/required checks (`float(data['preco'])`,
  `data['items']` iterated without checking it is a list), so wrong types or missing fields crash with 500.
- Each handler validates differently; some fields validated in one route and not in another.
- No check that the body is a JSON object.
Severity: MEDIUM.
Fix: P-11.

### AP-14 Error handling leaks internals or is not centralized
Report title: "Tratamento de erros inadequado".
Signals:
- `except Exception as e: return jsonify({"erro": str(e)}), 500` or `res.status(500).send(err.message)`.
- try/except blocks copied in every handler instead of one error handler/middleware.
- Errors swallowed (`except: pass`, empty `catch`), or callbacks that ignore `err`.
Severity: MEDIUM; HIGH when stack traces or SQL text reach the client.
Fix: P-12.

### AP-15 Duplicated code, serialization or constants
Report title: "Código duplicado".
Signals:
- The same row-to-dict mapping, validation block, query or constant list repeated in several places.
- Status/priority lists defined in a helper and again as literals in routes.
Severity: MEDIUM; LOW when it is only duplicated constants.
Fix: P-14, P-07.

### AP-16 Deprecated APIs
Report title: "Uso de APIs deprecated".
Signals (use `scripts/inventory.py` DEPRECATED lines as the primary source; confirm versions in Phase 1):

| API (signal) | Deprecated since | Modern equivalent |
|---|---|---|
| `datetime.utcnow()`, `datetime.utcfromtimestamp()` | Python 3.12 | `datetime.now(timezone.utc)` / `datetime.fromtimestamp(ts, timezone.utc)` (see P-13 for keeping the JSON format) |
| `Model.query.get(id)`, `.query.get_or_404(id)` | SQLAlchemy 2.0 (legacy `Query`) | `db.session.get(Model, id)`, `db.get_or_404(Model, id)` |
| `session.query(Model)` style | SQLAlchemy 2.0 (legacy, informational) | `db.session.execute(select(Model)).scalars()` |
| `@app.before_first_request` | Flask 2.3 (removed) | run the setup inside `create_app()` / `with app.app_context()` |
| `flask.json.JSONEncoder`, `app.json_encoder` | Flask 2.3 | `app.json = CustomJSONProvider(app)` |
| `res.send(status, body)`, `res.json(status, body)` | Express 4 | `res.status(status).send(body)` |
| `req.param(name)` | Express 4 | `req.params`, `req.query`, `req.body` |
| `res.sendfile()` | Express 4 | `res.sendFile()` |
| bare `bodyParser()` | body-parser 1.x / Express 4.16+ | `express.json()`, `express.urlencoded({ extended: false })` |
| `new Buffer(x)` | Node 6+ | `Buffer.from(x)`, `Buffer.alloc(n)` |
| `crypto.createCipher()` | Node 10 (removed in 22) | `crypto.createCipheriv()` with a random IV |
| `url.parse()` | Node 11+ (legacy) | `new URL(input, base)` |
| `fs.exists()` | Node 1+ | `fs.existsSync()` / `fs.promises.access()` |

Severity: MEDIUM when the API is removed or emits warnings in the installed version; LOW when only legacy-style.
Using MD5/SHA1 for passwords is NOT a deprecation finding: it is AP-05.
Fix: P-13.

## LOW

### AP-17 Magic numbers and strings
Report title: "Magic numbers / strings".
Signals: unexplained literals that encode rules (`if total > 1000: desconto = 0.1`, `status == 3`, `limit 50`,
`setTimeout(..., 86400000)`), repeated status strings.
Severity: LOW.
Fix: P-14.

### AP-18 Poor naming
Report title: "Nomenclatura ruim".
Signals: one-letter or cryptic names in business code (`u, e, p, cid, cc`), numbered variables (`cursor2`, `data3`),
names that shadow builtins (`id`, `type`, `list`, `input`), misleading names.
Severity: LOW.
Fix: P-14.

### AP-19 Dead code and unused imports
Report title: "Código morto / imports não utilizados".
Signals: imports never referenced, functions or variables never used (`totalRevenue` never read), commented-out code
blocks, unreachable branches.
Severity: LOW.
Fix: P-14.
