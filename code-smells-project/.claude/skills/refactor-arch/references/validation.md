# Phase 3 validation protocol

Phase 3 starts only after the user answered `s` to the Phase 2 question. This file is the authoritative Phase 3
procedure; when it differs from older instructions in your context, this file wins.

Variables used below: `SKILL_DIR` (directory of this skill), `PROJECT_ROOT` (the project being refactored),
`RUN_ROOT` (printed by `sandbox.py init`), `PY=python3 -I -B`, `C="$RUN_ROOT/contract"` (contract files).

## Safety rules (never break them)

1. Never execute project code inside `PROJECT_ROOT` (no `python app.py`, `npm start`, `flask run`, `pytest`, seeds,
   `py_compile`, `node --check` there). Run project code only through `sandbox.py run|serve|syntax`, which use
   disposable copies under `RUN_ROOT`.
2. Never open, copy, delete, migrate or recreate the project's data stores (`*.db`, `*.sqlite*`, `instance/`). The
   sandbox fingerprints them; any `DATA_GUARD=violation` stops Phase 3: report it to the user and do not continue.
3. Do not install, upgrade or remove dependencies (`pip install`, `npm install`, `npm ci`). Copies reuse the
   project's `.venv`/`node_modules` through symlinks. If a dependency is missing, stop and tell the user.
4. Never print secret values. Read code with `safe_view.py show`, review changes with `safe_view.py diff`.
5. Test cases must not trigger real external side effects (e-mail, payment gateways, third-party HTTP). If a route
   would contact an external host, leave that case out of the contract and say so in the summary.
6. Edit only the project's source files. Do not edit files under `.agents/`, `.claude/`, `reports/`, `.git/`, the data
   stores, or dependency directories.

## Step 1: baseline contract (before editing anything)

```bash
$PY "$SKILL_DIR/scripts/sandbox.py" init --project-root "$PROJECT_ROOT"      # -> RUN_ROOT=...
mkdir -p "$C"
$PY "$SKILL_DIR/scripts/sandbox.py" copy --run-root "$RUN_ROOT" --name baseline-src
```

1. `routes.txt`: one `METHOD /path` line per `ENDPOINT` line of `inventory.py` (use the inventory paths verbatim:
   Flask converters like `/tasks/<int:task_id>`, Express params like `/api/users/:id`). Every inventoried route is in
   the file.
2. Start command: the original one (`COMMAND start` from the inventory), plus the seed command first when the project
   needs one to have data (`COMMAND seed`). Use the project interpreter, e.g. `.venv/bin/python app.py` or
   `node src/app.js`, with the port passed through the project's own mechanism (env var or default port). Pick a free
   port; `sandbox.py serve` refuses busy ports.
3. `success.jsonl`: one case per route that returns 2xx on the seeded data, in the order a client would use them
   (reads before writes, `DELETE` last). Use ids that exist in the seed. Case format: `id`, `method`, `path`,
   optional `query`, `headers`, `body` (any JSON) or `raw_body`, optional `expect_status`.
4. Generate the complete contract and the list of literal 4xx messages:
   ```bash
   $PY "$SKILL_DIR/scripts/contract.py" scaffold --routes "$C/routes.txt" --success "$C/success.jsonl" \
       --source "$RUN_ROOT/copies/baseline-src" --out "$C/cases.jsonl"
   ```
   `scaffold` adds, mechanically: malformed JSON body, `null` body, wrong top-level type, for every field of the first
   2xx body another scalar type, a list (or object), `null` and a missing key, non-numeric numeric query params, an
   invalid value for each typed path converter, one unknown URL (404) and one unregistered method (405). Do not delete
   generated cases.
5. For every `MESSAGE file:line status=N` line, add one case to `success.jsonl` that triggers that business-rule
   response (for example a duplicate e-mail, stock too low, an id that does not exist) and run `scaffold` again.
6. Find the cases that crash the original server. Legacy code often dies on bad input (an uncaught exception kills
   the process), and every later case would then fail with `000`. Repeat on a fresh copy each time until
   `DEFER_UPDATED=no`; each round moves the first crashing case to `$C/defer.json`, which is replayed last:
   ```bash
   for n in $(seq 1 20); do
     $PY "$SKILL_DIR/scripts/sandbox.py" copy --run-root "$RUN_ROOT" --name "probe-$n" --from "$RUN_ROOT/copies/baseline-src"
     $PY "$SKILL_DIR/scripts/sandbox.py" serve --run-root "$RUN_ROOT" --name "probe-$n" --port "$PORT" --ready / \
         -- <start command> \
         --then -- python3 -I -B "$SKILL_DIR/scripts/contract.py" replay --base-url "http://127.0.0.1:$PORT" \
            --cases "$C/cases.jsonl" --record "$C/probe-$n.jsonl" --defer "$C/defer.json" --update-defer \
       > "$C/probe-$n.out"
     grep -E '^(SERVER_READY|DISCONNECTED|DEFER_UPDATED|DATA_GUARD)' "$C/probe-$n.out"
     grep -q '^DEFER_UPDATED=no' "$C/probe-$n.out" && break
   done
   ```
   No crash: `defer.json` is never created and `--defer` is a no-op. Crash cases keep status `000` in the baseline
   (`deferred: true`); Step 2 must give each one an approved `expect_status`, or Phase 3 stops to ask the user.
7. Record the baseline twice, each time on a fresh copy (state is mutated by the cases), always with
   `--defer "$C/defer.json"` (the same flag goes on the candidate replay in Step 4, so the order is identical):
   ```bash
   for n in 1 2; do
     $PY "$SKILL_DIR/scripts/sandbox.py" copy --run-root "$RUN_ROOT" --name "baseline-$n" --from "$RUN_ROOT/copies/baseline-src"
     $PY "$SKILL_DIR/scripts/sandbox.py" serve --run-root "$RUN_ROOT" --name "baseline-$n" --port "$PORT" --ready / \
         -- <start command> \
         --then -- python3 -I -B "$SKILL_DIR/scripts/contract.py" replay --base-url "http://127.0.0.1:$PORT" \
            --cases "$C/cases.jsonl" --record "$C/baseline-$n.jsonl" --defer "$C/defer.json"
   done
   ```
   `replay` exits 1 when a case misses its own `expect_status` or a non-deferred case gets no answer (`000`); the
   baseline cases must describe the original behavior, so fix the case (not the code) until both baselines pass.
8. Coverage gate:
   ```bash
   $PY "$SKILL_DIR/scripts/contract.py" coverage --routes "$C/routes.txt" --record "$C/baseline-1.jsonl" \
       --source "$RUN_ROOT/copies/baseline-src"
   ```
   It must print `COVERAGE=ok`. A gap you cannot reach (for example a branch that needs an external service) goes into
   `$C/unreachable.json` (`[{"gap": "<exact gap text>", "reason": "..."}]`) passed with `--unreachable`, and into the
   final summary.

## Step 2: approved contract changes -> candidate expectations

The candidate contract is derived mechanically from the complete baseline. Every baseline case id is replayed
against the refactored code with the same request; only the approved contract changes may alter expectations.

1. Write `$C/approved-plan.json` with one entry per approved item of the report section "Alterações de contrato"
   (C1, C2, ...). Nothing else may go in it:
   ```json
   {"changes": [
     {"reason": "C1: remove password from user responses (achado 3)",
      "match": {"route": "GET /users*"}, "forbid_keys": ["password"]},
     {"reason": "C2: admin routes require X-Admin-Token (achado 1)",
      "match": {"route": "POST /admin/*"}, "set_headers": {"X-Admin-Token": "test-admin-token"},
      "add_cases": [{"id": "add-admin-no-token", "method": "POST", "path": "/admin/reset-db", "expect_status": [401]}]},
     {"reason": "C3: invalid JSON bodies answer 400 instead of 500 (achado 7)",
      "match": {"baseline_status": 500, "body_kind": "malformed"}, "expect_status": [400]}
   ]}
   ```
   `match` keys: `id` (glob), `route` (`METHOD /glob` on the concrete path), `baseline_status`, `json`, `body_kind`.
   Actions: `forbid_keys`, `set_headers`, `expect_status`, `expect_json_keys`, `allow` (`[{"kind", "path"}]`),
   `add_cases` (ids start with `add-`). A change of a 2xx/4xx baseline status needs `"changes_success": true` and
   must be literally approved.
   Every crash case (baseline status 0, `deferred: true`) needs an approved `expect_status`; `match` accepts
   `"baseline_status": 0` (e.g. `{"reason": "C3 ...", "match": {"baseline_status": 0}, "expect_status": [400]}`).
   `derive` refuses crash cases without one; `compare` checks only their status, since the original never answered.
   Every case whose baseline answered 5xx needs a decision, because `compare` rejects any 5xx in the candidate,
   even when the code did not change: either an approved fix (e.g.
   `{"reason": "C3 ...", "match": {"baseline_status": 500, "route": "POST /tasks"}, "expect_status": [400]}`) or,
   only if the user approved keeping that crash, `{"reason": "C4 ...", "match": {"baseline_status": 500},
   "allow": [{"kind": "candidate_5xx"}]}`. Count the baseline 5xx cases before writing the plan
   (`grep -c '"status": 5' "$C/baseline-1.jsonl"`); if the approved report does not cover them, stop and ask.
2. Derive:
   ```bash
   $PY "$SKILL_DIR/scripts/contract.py" derive --cases "$C/cases.jsonl" --record "$C/baseline-1.jsonl" \
       --plan "$C/approved-plan.json" --out-cases "$C/candidate.cases.jsonl" --out-allow "$C/allow.json"
   ```
   Never edit `candidate.cases.jsonl` or `allow.json` by hand.

What counts as a contract change (each needs an approved item, otherwise it is a regression):
- any status code change, including 500 -> 400 for bad input and 404/405 changes;
- a content-type change, including the framework's default HTML/text error pages (404, 405, 500) becoming JSON;
- added or removed JSON keys, a changed value type (int -> float, string -> object), a changed message text;
- different deterministic values for the seeded data (ids, counts, totals, names, list lengths, order).

## Step 3: refactor

Follow `references/mvc-guidelines.md` and `references/refactoring-playbook.md`. Work in small steps. After each
significant step, check syntax and boot on a fresh copy:

```bash
$PY "$SKILL_DIR/scripts/sandbox.py" copy --run-root "$RUN_ROOT" --name "step-$k"
$PY "$SKILL_DIR/scripts/sandbox.py" syntax --run-root "$RUN_ROOT" --name "step-$k"
```

## Step 4: acceptance gates (all must pass on the final code)

1. Candidate replay on a fresh copy of the refactored project, same start command and port rules:
   ```bash
   $PY "$SKILL_DIR/scripts/sandbox.py" copy --run-root "$RUN_ROOT" --name candidate
   $PY "$SKILL_DIR/scripts/sandbox.py" serve --run-root "$RUN_ROOT" --name candidate --port "$PORT" --ready / \
       --env ADMIN_TOKEN=test-admin-token -- <start command> \
       --then -- python3 -I -B "$SKILL_DIR/scripts/contract.py" replay --base-url "http://127.0.0.1:$PORT" \
          --cases "$C/candidate.cases.jsonl" --record "$C/candidate.jsonl" --defer "$C/defer.json"
   ```
   The server must boot (`SERVER_READY=yes`), stop cleanly (`PORT_FREE=yes`), and the guard must say `DATA_GUARD=ok`.
2. Compare:
   ```bash
   $PY "$SKILL_DIR/scripts/contract.py" compare --baseline "$C/baseline-1.jsonl" --rerun "$C/baseline-2.jsonl" \
       --candidate "$C/candidate.jsonl" --allow "$C/allow.json"
   ```
   It must print `COMPARE=ok` with `UNAPPROVED=0`. Values that differ between the two baselines (timestamps, random
   tokens) are volatile and ignored automatically; everything else is compared: status, content type, JSON vs non-JSON,
   keys, types, messages, values and text bodies. Any candidate 5xx is a failure.
   When it fails, fix the code. Do not add plan entries or allow rules for differences the user did not approve. If you
   believe an unapproved difference is necessary, stop and ask the user, citing the case id and the diff kind.
3. Structure: `$PY "$SKILL_DIR/scripts/check_mvc.py" --project-root "$PROJECT_ROOT"` prints `MVC=ok`.
4. Findings: every finding of the approved report is fixed, or listed in the summary as not fixed with the reason.
   Search the refactored code for the secret literals the report cited (by line, with `safe_view.py show`): none may
   remain.
5. Review the diff without secrets: `$PY "$SKILL_DIR/scripts/safe_view.py" diff --project-root "$PROJECT_ROOT"`.
6. Clean up: `$PY "$SKILL_DIR/scripts/sandbox.py" finish --run-root "$RUN_ROOT"` prints `FINISH=ok`. Nothing new may be
   left in the project (`__pycache__`, `*.pyc`, databases, logs, contract files).

## Phase 3 summary (pt-BR, final message)

```text
================================
FASE 3: REFATORAÇÃO CONCLUÍDA
================================
## Nova estrutura
<tree>

## Achados tratados
- Achado 1 (AP-01) -> <what changed, files>
...

## Alterações de contrato aplicadas
- C1 ... (exatamente as aprovadas)

## Validação
- Boot: <start command> -> SERVER_READY=yes, PORT_FREE=yes
- Contrato: CASES=<n> PAIRED=<n> UNAPPROVED=0 VOLATILE=<n> (COMPARE=ok)
- Cobertura: COVERAGE=ok (<unreachable gaps, if any>)
- Estrutura: MVC=ok
- Dados: DATA_GUARD=ok em todas as execuções; FINISH=ok

## Pendências
<not fixed findings with reason, or "Nenhuma">
================================
```
Report only results you actually obtained from the helper output in this session.
