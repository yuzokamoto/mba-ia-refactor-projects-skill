# Refactoring playbook (knowledge area 5)

Concrete transformations for Phase 3. Each finding of the approved report points to one or more `P-NN`. The examples
are patterns; adapt names to the project and keep every observable HTTP behavior that is not an approved contract
change (status, JSON keys, messages, value types, seed data). Code comments in the refactored project follow the
project's language (pt-BR here).

## P-01 Externalize configuration and secrets

Before (Flask):
```python
app = Flask(__name__)
app.config["SECRET_KEY"] = "<literal>"
app.config["DEBUG"] = True
```
After:
```python
# config/settings.py
import os

class Settings:
    SECRET_KEY = os.environ.get("SECRET_KEY")          # sem valor padrão literal
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "loja.db")

# app.py
def create_app(settings=Settings):
    app = Flask(__name__)
    app.config.from_object(settings)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = os.urandom(32).hex()  # efêmero em dev; produção define a variável
    return app
```
Before (Express): `const config = { dbPass: "<literal>", paymentGatewayKey: "<literal>", port: 3000 };`
After:
```js
// src/config/index.js
module.exports = {
  port: Number(process.env.PORT || 3000),
  dbPass: process.env.DB_PASS,                 // sem literal
  paymentGatewayKey: process.env.PAYMENT_GATEWAY_KEY,
};
```
Keep the default port and non-secret defaults so the start command still works. Add a `.env.example` with the variable
names only (no values).

## P-02 Parameterized queries

Before:
```python
cursor.execute("SELECT * FROM usuarios WHERE email = '" + email + "' AND senha = '" + senha + "'")
```
After:
```python
cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
```
JS before: ``db.all(`SELECT * FROM courses WHERE id = ${id}`, cb)`` -> after: `db.all("SELECT * FROM courses WHERE id = ?", [id], cb)`.
Dynamic `ORDER BY`/column names: map user input through an allow-list dict; never interpolate it.

## P-03 Password hashing

Before: `self.password = hashlib.md5(pwd.encode()).hexdigest()` / `WHERE senha = ?` with the raw password.
After (Flask/Werkzeug is already a dependency of Flask):
```python
from werkzeug.security import generate_password_hash, check_password_hash

def set_password(self, raw):
    self.password = generate_password_hash(raw)

def check_password(self, raw):
    if self.password and self.password.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(self.password, raw)
    # registros antigos (MD5/texto puro): valida uma vez e migra para o hash novo
    legacy_ok = self.password in (raw, hashlib.md5(raw.encode()).hexdigest())
    if legacy_ok:
        self.set_password(raw)
    return legacy_ok
```
Node: use `crypto.scryptSync(raw, salt, 64)` with a random salt stored as `salt:hash`, compared with
`crypto.timingSafeEqual`; no new npm dependency needed. Login with existing seed users must keep working; the stored
hash is never returned by the API (P-04).

## P-04 Stop exposing sensitive data

Before: `def to_dict(self): return {"id": ..., "email": ..., "password": self.password}`;
`console.log(\`Processando cartão ${cc} na chave ${config.paymentGatewayKey}\`)`.
After:
```python
PUBLIC_FIELDS = ("id", "name", "email", "role", "active", "created_at")

def to_dict(self):
    return {field: getattr(self, field) for field in PUBLIC_FIELDS}
```
```js
logger.info(`Processando pagamento do usuário ${userId}`); // sem cartão nem chave
```
Health/debug endpoints return status only, never config values. Removing keys from a response is a contract change
(list it in Phase 2).

## P-05 Protect sensitive endpoints

Before: `@app.route("/admin/reset-db", methods=["POST"])` with no check; `/admin/query` executing client SQL.
After:
```python
# middlewares/auth.py
from functools import wraps
from flask import current_app, jsonify, request
import hmac

def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = current_app.config.get("ADMIN_TOKEN")
        given = request.headers.get("X-Admin-Token", "")
        if not expected or not hmac.compare_digest(given, expected):
            return jsonify({"erro": "Não autorizado"}), 401
        return view(*args, **kwargs)
    return wrapper
```
```js
// src/middlewares/auth.js
module.exports = (config) => (req, res, next) => {
  const token = req.get("X-Admin-Token") || "";
  if (!config.adminToken || token !== config.adminToken) return res.status(401).json({ error: "Unauthorized" });
  next();
};
```
Arbitrary-SQL endpoints are removed or answer 403/404, as approved. The header name, status and messages are exactly the
ones listed in the approved contract change.

## P-06 Split a God class / God module

Before: `class AppManager { constructor() { this.db = new sqlite3.Database(':memory:'); this.initDb(); } setupRoutes(app) { app.post('/api/checkout', (req, res) => { /* 80 lines */ }) } }`
After:
```text
src/
  config/index.js          # porta, variáveis de ambiente
  models/db.js             # abre conexão, cria schema, seed (mesmos dados)
  models/user.model.js     # findByEmail, create
  models/course.model.js   # findActiveById, list
  services/checkout.service.js   # regra de checkout em transação
  controllers/checkout.controller.js
  routes/checkout.routes.js
  middlewares/errorHandler.js
  app.js                   # compõe tudo; server.js chama listen
```
Move code first (same behavior), then fix the findings in the new places. Keep the seed data identical (ids, names,
amounts) so deterministic responses stay equal.

## P-07 Extract business logic from route handlers (fat controllers)

Before:
```python
@task_bp.route("/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    data = request.get_json()
    if "status" in data and data["status"] not in ["pending", "in_progress", "done"]:
        return jsonify({"error": "Invalid status"}), 400
    ...
    db.session.commit()
    return jsonify(task.to_dict()), 200
```
After:
```python
# routes/task_routes.py
task_bp.add_url_rule("/tasks/<int:task_id>", view_func=task_controller.update_task, methods=["PUT"])

# controllers/task_controller.py
def update_task(task_id):
    data = task_validator.update_payload(request.get_json(silent=True))
    task = task_service.update_task(task_id, data)
    return jsonify(task.to_dict()), 200

# services/task_service.py
def update_task(task_id, data):
    task = task_model.get_by_id(task_id)
    if task is None:
        raise NotFoundError("Task not found")
    if "status" in data and data["status"] not in VALID_STATUSES:
        raise ValidationError("Invalid status")
    ...
    task_model.save(task)
    return task
```
The controller maps `NotFoundError -> 404` and `ValidationError -> 400` with the same JSON keys as before (P-12).

## P-08 Replace global state and shared connections

Before: `conn = sqlite3.connect("loja.db", check_same_thread=False)` at import time; `let globalCache = {}` mutated by
requests.
After (Flask):
```python
# models/database.py
from flask import current_app, g

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_app(app):
    app.teardown_appcontext(close_db)
```
Express: create the `sqlite3.Database` once in `models/db.js` and inject it into models (P-15); remove module-level
caches/counters or encapsulate them in a service with explicit lifetime.

## P-09 Wrap multi-step writes in a transaction

Before: insert order, insert items, update stock with separate `commit()` calls / nested callbacks.
After:
```python
def create_order(user_id, items):
    db = get_db()
    try:
        with db:                                # commit no sucesso, rollback em exceção
            order_id = order_model.insert(db, user_id)
            for item in items:
                product_model.decrement_stock(db, item["produto_id"], item["quantidade"])
                order_model.insert_item(db, order_id, item)
    except InsufficientStockError:
        raise
    return order_id
```
```js
await run(db, "BEGIN");
try { /* inserts/updates */ await run(db, "COMMIT"); } catch (err) { await run(db, "ROLLBACK"); throw err; }
```
Validate stock for all items before writing, so the error message and status stay the same as before.

## P-10 Remove N+1 queries

Before: `for order in orders: cursor.execute("SELECT * FROM itens_pedido WHERE pedido_id = ?", (order["id"],))`.
After:
```python
rows = db.execute("SELECT * FROM itens_pedido WHERE pedido_id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
items_by_order = defaultdict(list)
for row in rows:
    items_by_order[row["pedido_id"]].append(dict(row))
```
SQLAlchemy: `select(Task).options(selectinload(Task.user))`; counts with `func.count()` and `group_by`. Keep the
response order (add `ORDER BY` matching the old iteration order).

## P-11 Centralize input validation

Before: `preco = float(data["preco"])` inside the handler (500 on wrong type or missing key).
After:
```python
# validators/product_validator.py
def create_payload(data):
    if not isinstance(data, dict):
        raise ValidationError("Dados inválidos")
    errors = []
    if not isinstance(data.get("nome"), str) or not data["nome"].strip():
        errors.append("Nome é obrigatório")
    if not isinstance(data.get("preco"), (int, float)) or isinstance(data.get("preco"), bool):
        errors.append("Preço inválido")
    if errors:
        raise ValidationError(errors[0])
    return data
```
Keep the original messages for cases that already returned 4xx. New 400 responses for inputs that crashed before are a
contract change; list them in Phase 2.

## P-12 Centralized error handling and safe runtime defaults

Before: `except Exception as e: return jsonify({"erro": str(e)}), 500` in every handler; `app.run(debug=True,
host="0.0.0.0")`.
After:
```python
# middlewares/error_handler.py
def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(exc):
        return jsonify({exc.key: exc.message}), exc.status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return exc                      # mantém as páginas padrão (404/405) se o contrato não mudou
        app.logger.exception("Erro inesperado")
        return jsonify({"erro": "Erro interno"}), 500
```
```js
// src/middlewares/errorHandler.js
module.exports = (err, req, res, next) => {
  if (err.status) return res.status(err.status).json({ error: err.message });
  console.error(err);
  res.status(500).json({ error: "Internal server error" });
};
```
`debug` and bind host come from config (P-01). Do not convert framework HTML 404/405 pages to JSON unless the approved
contract says so; returning `exc` for `HTTPException` keeps them.

## P-13 Replace deprecated APIs without changing output

- `datetime.utcnow()` -> `datetime.now(timezone.utc).replace(tzinfo=None)` when the value is stored or serialized as a
  naive UTC timestamp (keeps the same `isoformat()` text); use the aware value only if the contract change is approved.
- `Model.query.get(id)` -> `db.session.get(Model, id)`; `Model.query.get_or_404(id)` -> `db.get_or_404(Model, id)`.
- `Model.query.filter_by(...).all()` -> `db.session.execute(select(Model).filter_by(...)).scalars().all()`.
- Express `res.send(404, body)` -> `res.status(404).send(body)`; `req.param("id")` -> `req.params.id`; bare
  `bodyParser()` -> `express.json()`; Node `new Buffer(x)` -> `Buffer.from(x)`.

## P-14 Constants, naming and dead code

Before: `if total > 1000: desconto = 0.1`; `u, e, p = req.body...`; unused imports, `totalRevenue` never read.
After:
```python
DISCOUNT_THRESHOLD = 1000
DISCOUNT_RATE = 0.1
VALID_STATUSES = ("pending", "in_progress", "done", "cancelled")
```
```js
const { name, email, password } = req.body;
```
Delete unused code and imports; define each constant once (models or a `constants` module) and import it.

## P-15 Dependency injection and app factory

Before: modules create their own connections/services at import time; tables created on import.
After:
```python
def create_app(settings=Settings):
    app = Flask(__name__)
    app.config.from_object(settings)
    database.init_app(app)
    register_blueprints(app)
    register_error_handlers(app)
    return app

if __name__ == "__main__":
    create_app().run(host=Settings.HOST, port=Settings.PORT, debug=Settings.DEBUG)
```
```js
// src/app.js
function buildApp({ db, config }) {
  const app = express();
  app.use(express.json());
  app.use("/api", buildRoutes({ controllers: buildControllers({ services: buildServices({ db, config }) }) }));
  app.use(errorHandler);
  return app;
}
```
Seeding stays where the original project did it (on startup or in `seed.py`), with the same data.
