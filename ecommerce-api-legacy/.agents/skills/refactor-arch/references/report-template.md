# Phase 2 report template (knowledge area 3)

The final message of Phases 1-2 is ONE text, in Brazilian Portuguese, with exactly these parts in this order:
1. the Phase 1 block (`references/project-analysis.md`);
2. the audit report below;
3. the confirmation question as the very last line.

`scripts/check_report.py` validates that text. Run it before you answer (see SKILL.md, step 2.5) and fix every
`PROBLEM` line. Do not add content after the question.

## Layout (copy the structure literally; replace `<...>`)

```text
================================
RELATÓRIO DE AUDITORIA ARQUITETURAL
================================
Projeto: <directory name of the project>
Stack:   <language + runtime version> + <framework + version>
Arquivos: <N> analisados | <LOC> linhas de código

## Resumo
CRITICAL: <a> | HIGH: <b> | MEDIUM: <c> | LOW: <d>

## Achados

### 1. [CRITICAL] <short title in pt-BR> (AP-NN)
Arquivo: <path:line or path:start-end>; <more locations of the same root cause>
Descrição: <what the code does, citing names, never secret values>
Impacto: <concrete consequence>
Recomendação: <what Phase 3 will do> (P-NN)

### 2. [HIGH] <title> (AP-NN/AP-MM)
Arquivo: ...
Descrição: ...
Impacto: ...
Recomendação: ...

<... one block per finding ...>

## Plano proposto e alterações de contrato

### Estrutura alvo
<tree of the target MVC layout, see references/mvc-guidelines.md>

### Transformações
- Achado 1 -> P-01: <one line>
- Achado 2 -> P-02, P-12: <one line>
<... every finding appears here ...>

### Alterações de contrato
- C1. <routes affected> — antes: <observable behavior today> — depois: <behavior after Phase 3> — motivo: achado <n>.
- C2. ...
<or exactly: "Nenhuma: todas as respostas HTTP observáveis são preservadas.">

### Preservado
<what stays identical: routes, methods, status codes, JSON keys and values, messages, seed data, start commands>

### Cobertura
<checks you made that produced no finding, and checks you could not confirm statically, one line each>

================================
Total: <N> achados
================================

Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]
```

## Rules

- Field labels are exact: `Projeto:`, `Stack:`, `Arquivos:` in the header; `Arquivo:`, `Descrição:`, `Impacto:`,
  `Recomendação:` in each finding, each on its own line with a non-empty value.
- Finding headings: `### <n>. [<SEVERITY>] <title> (AP-NN[/AP-MM])`, numbered from 1 without gaps, ordered
  CRITICAL -> HIGH -> MEDIUM -> LOW. No other `###` heading inside `## Achados`.
- `## Resumo` counts and `Total: <N> achados` must equal the findings listed.
- `Arquivo:` items are `relative/path.ext:line` or `relative/path.ext:start-end`, separated by `;`, relative to the
  project root, no backticks, no absolute paths. Every line number must exist in the file.
- At least 5 findings, with at least one CRITICAL or HIGH. Report everything you confirmed; do not pad with
  unconfirmed items to reach a number.
- Never copy a secret value, password, token, card number or key into the report. Name the variable and cite the line.
- The confirmation question is the last non-empty line, exactly:
  `Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]`

## Contract changes (`### Alterações de contrato`)

Phase 3 must keep every observable HTTP behavior of the original code except the changes listed here and approved by
the user. "Observable" means: route + method, status code, content type (JSON vs HTML/text), JSON keys and value
types, deterministic values (ids, counts, seed data), and error messages. List a change when the fix of a finding
alters any of these. Typical ones:

- removing secret/password/hash keys from responses (name the keys and the routes);
- requiring a token on admin/destructive routes (name the routes, the header, the status without/with an invalid
  token, and where the token comes from: an environment variable; without it the routes stay disabled);
- invalid input that crashes today (500 or a dropped connection) answering 400 with a JSON error;
- framework default error pages (HTML 404/405/500) becoming JSON, if you plan a JSON error handler for them;
- removing an endpoint (for example one that executes arbitrary SQL) or changing its status;
- any change of status code, message text, value type (int -> float, naive -> timezone-aware dates) or seed data.

Each item names its routes precisely (method + path pattern) so that Phase 3 can turn it into one mechanical rule.
Anything not listed must stay identical, including messages and the HTML of framework error pages.
