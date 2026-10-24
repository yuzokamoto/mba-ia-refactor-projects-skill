---
name: refactor-arch
description: "Audit a legacy web API (Flask, Express or similar) and refactor it to MVC in three phases: project analysis, architecture audit report with anti-patterns by severity, a stop for user approval, then refactoring validated against the original HTTP contract."
---

# refactor-arch

Audits a legacy web API and refactors it to MVC in three sequential phases: (1) project analysis, (2) architecture
audit report, then a mandatory stop for the user's approval, (3) refactoring with mechanical validation. Works for any
stack the helpers recognize (Python/Flask, Node.js/Express and similar). Everything shown to the user is written in
Brazilian Portuguese (pt-BR).

## Setup (do this first, every session)

```bash
PROJECT_ROOT="$(pwd)"                      # the project directory the user opened
SKILL_DIR="$PROJECT_ROOT/.agents/skills/refactor-arch"      # directory that contains this SKILL.md
PY="python3 -I -B"
test -f "$SKILL_DIR/scripts/inventory.py" && echo SKILL_OK
```

If `SKILL_OK` is not printed, locate the directory of this SKILL.md and set `SKILL_DIR` to it. Shell variables do not
persist between commands in every environment: repeat the three assignments in each command, or use absolute paths.

## Rules for every phase

- Phases 1 and 2 are read-only: do not create, edit or delete files, do not run project code or tests, do not install
  dependencies, do not start servers. Only the helper scripts below are run, always with `python3 -I -B`.
- Never open the project's data stores (`*.db`, `*.sqlite*`, `instance/`).
- Read source files only with `"$SKILL_DIR/scripts/safe_view.py" show` (it hides secret values and keeps names and
  line numbers). Never print secret values, passwords, tokens or card numbers in commands, outputs or reports.
- The helper outputs are the source of truth for counts, versions, endpoints and validation results. Do not report a
  number or a result you did not get from a helper or from reading the code in this session.

## Phase 1: project analysis

1. Read `references/project-analysis.md`.
2. Run `$PY "$SKILL_DIR/scripts/inventory.py" --project-root "$PROJECT_ROOT"`.
3. Read the entry point, the manifests and enough source to describe domain, architecture and database.
4. Prepare the Phase 1 block exactly as in `references/project-analysis.md`, with the inventory totals.

## Phase 2: architecture audit

1. Read `references/anti-patterns.md` and `references/report-template.md`.
2. Read every source file listed by the inventory (`FILE` lines) with `safe_view.py show`. Check each file against
   every catalog entry (AP-01 to AP-19), and include the inventory `DEPRECATED` lines (AP-16).
3. Keep only confirmed findings: each one cites lines you read that show the problem. One root cause = one finding.
4. Plan the refactoring and list every observable behavior change in `### Alterações de contrato`
   (`references/report-template.md`).
5. Validate the whole answer (Phase 1 block + report + final question) before showing it, without writing files:
   ```bash
   $PY "$SKILL_DIR/scripts/check_report.py" --project-root "$PROJECT_ROOT" - <<'REPORT_EOF'
   <the complete answer text>
   REPORT_EOF
   ```
   Fix every `PROBLEM` line and run it again until it prints `RESULT=ok`.
6. Answer with exactly the validated text. Its last line is:
   `Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]`
7. STOP. Do not start Phase 3 in the same turn. Phase 3 starts only when the user explicitly approves (`s`, `sim`,
   or an approval message). Any other answer: answer questions or adjust the report, and ask again.

## Phase 3: refactoring (only after approval)

1. Read `references/validation.md` (authoritative Phase 3 procedure), `references/mvc-guidelines.md` and
   `references/refactoring-playbook.md`.
2. Follow `references/validation.md` steps 1 to 4 in order: baseline contract on disposable copies, approved contract
   changes, refactoring, acceptance gates (`COMPARE=ok`, `MVC=ok`, `DATA_GUARD=ok`, `FINISH=ok`).
3. Apply only the contract changes the user approved. If an unapproved behavior change seems necessary, stop and ask.
4. Finish with the Phase 3 summary from `references/validation.md`, reporting only results the helpers printed.
