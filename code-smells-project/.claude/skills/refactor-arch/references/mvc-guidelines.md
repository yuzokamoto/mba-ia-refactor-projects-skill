# MVC target architecture (knowledge area 4)

Phase 3 restructures the project into the layers below. `scripts/check_mvc.py` is the mechanical gate: Phase 3 is
not done while it prints `MVC=failed`. Passing the gate is necessary, not sufficient: the layers must also do what
this file says.

## Layers and responsibilities

| Layer | Python (Flask) | Node.js (Express) | Responsibility | Must NOT contain |
|---|---|---|---|---|
| config | `config/settings.py` (or `config.py`) | `src/config/index.js` | read environment variables, defaults that are not secrets, paths | secret literals, DB access, routes |
| entry / app factory | `app.py` with `create_app()` | `src/app.js` (builds app) + `src/server.js` (listens) | create the app, load config, init DB, register routes and error handlers, start | handlers longer than 8 code lines, SQL, business rules |
| routes (views) | `routes/<resource>_routes.py` (Blueprints) | `src/routes/<resource>.routes.js` (Router) | map method + path to a controller function, attach middlewares/validators | queries, imports of models/services/database, logic |
| controllers | `controllers/<resource>_controller.py` | `src/controllers/<resource>.controller.js` | HTTP flow: read params/body, call validator, call service/model, choose status and build the response | SQL, persistence, business rules, string dispatch |
| validators | `validators/<resource>_validator.py` | `src/validators/<resource>.validator.js` | check body/query shape and types, return messages | DB access, HTTP response objects |
| services | `services/<resource>_service.py` | `src/services/<resource>.service.js` | business rules and multi-step operations (transactions), orchestration of models | `request`, `jsonify`, `req`/`res`, HTTP status codes, route definitions |
| models (and repositories) | `models/<resource>.py` | `src/models/<resource>.model.js` | data structure, persistence, queries, serialization of public fields | HTTP objects, status codes, request parsing |
| middlewares | `middlewares/error_handler.py`, `middlewares/auth.py` | `src/middlewares/errorHandler.js`, `src/middlewares/auth.js` | centralized error handling, authentication/authorization guards, logging | business rules |
| errors | `errors.py` / `utils/errors.py` | `src/errors/AppError.js` | domain exceptions with a status-independent meaning (`NotFoundError`, `ValidationError`, `ConflictError`) | HTTP objects |

Flow: `route -> (middleware/validator) -> controller -> service -> model -> database`. Errors flow back as domain
exceptions; the controller or the central error handler maps them to HTTP status + JSON body. Services never know
the HTTP status.

## Mapping domain errors to HTTP (keeps the contract)

Keep the exact status codes and messages of the original code unless an approved contract change says otherwise.
The usual pattern: services raise `NotFoundError("Tarefa não encontrada")`; the controller/error handler maps
`NotFoundError -> 404`, `ValidationError -> 400`, `ConflictError -> 409`, `AuthError -> 401`, `ForbiddenError -> 403`
and renders the original JSON shape (`{"error": msg}`, `{"erro": msg}`, plain text, whatever the endpoint used).
When different endpoints used different shapes for the same error, keep each endpoint's shape: pass the shape from the
controller (for example a small `respond_error(exc, key="erro")` helper) instead of unifying it.

## Adapting to the starting point

- Flat Flask monolith (`app.py`, `controllers.py`, `models.py`, `database.py`): create the folders, move each SQL
  function into `models/<resource>.py` with parameterized queries, rules into `services/`, keep Flask handlers thin in
  `controllers/` and `routes/`. Keep `database.py` (connection lifecycle) under `models/` or `config/`, or keep the
  file and expose `get_db()` used only by models.
- Partially layered Flask (`models/`, `routes/`, `services/`, `utils/`): the folders exist but the routes hold the
  logic. Add `controllers/` and `validators/`, move queries out of routes into model/repository functions, move rules
  into services, keep `models/` as SQLAlchemy classes plus query functions. Keep the existing module names when they
  already mean the right thing (e.g. `services/notification_service.py`).
- Express god class (`AppManager.js` doing DB setup + routes + checkout): split into `src/config`, `src/models`
  (one file per table with promise-wrapped queries), `src/services` (checkout/enrollment flow in a transaction),
  `src/controllers`, `src/routes`, `src/middlewares/errorHandler.js`; `src/app.js` composes them; keep the original
  start command (`npm start`, `node src/app.js`) working.
- Keep the start command, port, environment variable names and seed behavior of the original project. If a new
  environment variable is introduced (e.g. `ADMIN_TOKEN`), it is optional unless an approved contract change says the
  feature is disabled without it.

## Forbidden shapes (they fail `check_mvc.py` or the review)

- Moving route handlers into `services/handlers/*.py` or similar and calling it MVC (`route_outside_http_layer`,
  `http_in_domain`).
- A pass-through helper that returns a query/session/connection used by routes or controllers
  (`def model_query(m): return m.query`) (`db_access_via_helper`).
- One controller that serves every resource through a string dispatcher (`dispatch("create_task")`,
  `getattr(service, action)`, dict of action names) (`string_dispatch_controller`).
- One service or model file holding several resources and more than 300 code lines (`god_module`): split per resource.
- Services returning `(payload, 400)` tuples, `res.status(...)` or `{status: 404}` (`status_in_domain`).
- Controllers that are only `return service.x()` for every function while the service reads `request` (warning
  `pass_through_controller` plus `http_in_domain`).
- Routes importing models, services or the database (`routes_import_data`), or route functions longer than 8 code
  lines (`route_handler_too_long`).
- Leaving business logic in the entry file (`entry_has_handlers`, warning) or having routes without a controllers
  layer (`no_controller_layer`).

## Checklist before finishing Phase 3

- `python3 -I -B "$SKILL_DIR/scripts/check_mvc.py" --project-root "$PROJECT_ROOT"` prints `MVC=ok`.
- Every finding of the approved report is fixed or explicitly listed as not fixed with the reason.
- No secret literal remains in code; config reads environment variables (`P-01`).
- No file of the old structure is left as dead code; imports are updated; no unused modules remain.
