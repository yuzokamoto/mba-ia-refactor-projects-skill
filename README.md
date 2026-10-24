# Desafio: skill `refactor-arch` — auditoria e refatoração de APIs legadas para MVC

Fork de [devfullcycle/mba-ia-refactor-projects-skill](https://github.com/devfullcycle/mba-ia-refactor-projects-skill).
O enunciado original está no repositório base.

Este repositório contém uma skill reutilizável, `refactor-arch`, que analisa uma API legada, gera um relatório de
auditoria arquitetural por severidade, pede aprovação e então refatora o projeto para MVC, validando que os endpoints
continuam respondendo. A skill foi executada nos três projetos com o **OpenAI Codex CLI** usando o modelo
**gpt-6.1-sol** (raciocínio `high`).

| Projeto | Stack | Relatório (Fase 2) |
|---|---|---|
| `code-smells-project/` | Python 3 + Flask 3.1 (API de e-commerce) | [`reports/audit-project-1.md`](reports/audit-project-1.md) |
| `ecommerce-api-legacy/` | Node.js + Express 4 (LMS com checkout) | [`reports/audit-project-2.md`](reports/audit-project-2.md) |
| `task-manager-api/` | Python 3 + Flask 3.0 + SQLAlchemy (gerenciador de tarefas) | [`reports/audit-project-3.md`](reports/audit-project-3.md) |

A skill está nos três projetos em dois formatos com o mesmo conteúdo:

- `.claude/skills/refactor-arch/` — formato do enunciado (Claude Code, invocada com `/refactor-arch`);
- `.agents/skills/refactor-arch/` — formato do Codex CLI (invocada com `$refactor-arch`), o usado nas execuções.

`references/` e `scripts/` são idênticos byte a byte nas seis cópias.

---

## A) Análise Manual

Feita lendo o código original antes de escrever a skill. Serviu de gabarito para conferir se a Fase 2 encontrava os
problemas reais. Os valores de segredos foram omitidos de propósito.

### Projeto 1 — code-smells-project (Python/Flask, 4 arquivos, 780 linhas, 19 endpoints)

Monólito plano: `app.py` (rotas e SQL administrativo), `controllers.py`, `models.py` (persistência de todos os
recursos) e `database.py` (conexão global, esquema e seed).

| Severidade | Problema | Onde | Por que importa |
|---|---|---|---|
| CRITICAL | Endpoints administrativos sem autenticação, incluindo execução de SQL arbitrário | `app.py:47-78` (`/admin/reset-db`, `/admin/query`) | Qualquer cliente apaga o banco ou lê/altera qualquer tabela |
| CRITICAL | SQL injection por concatenação | `models.py:109-111` (login), `models.py:289-299` (busca) | Permite contornar o login e extrair ou modificar dados |
| CRITICAL | Senhas em texto puro | `models.py:105-111, 122-130`; `database.py:75-83` | Um vazamento do banco expõe credenciais reutilizáveis |
| CRITICAL | Dados sensíveis nas respostas | `models.py:79-85, 95-101`; `controllers.py:128-144, 276-290` | As listagens de usuários devolvem senhas; `/health` expõe a chave secreta |
| CRITICAL | `SECRET_KEY` fixa no código | `app.py:7` | O segredo vai junto com o código-fonte |
| HIGH | Conexão SQLite global com `check_same_thread=False` | `database.py:4-12` | Requisições concorrentes compartilham conexão e transação |
| HIGH | Pedido sem checagem consolidada de estoque nem rollback | `models.py:139-168` | Estoque negativo e escritas parciais |
| HIGH | Debug ligado e bind em `0.0.0.0` | `app.py:8, 88` | Depurador interativo exposto na rede |
| MEDIUM | Queries N+1 nas listagens de pedidos | `models.py:174-192, 206-224` | O número de consultas cresce com pedidos × itens |
| MEDIUM | Validação de entrada inconsistente | `controllers.py:24-54, 64-96` | Tipos errados geram 500 ou dados inválidos |
| MEDIUM | Serialização duplicada | `models.py:12-21, 31-40, 304-313` | Uma mudança de campo precisa ser repetida em vários lugares |
| MEDIUM | Exceções internas devolvidas ao cliente | `controllers.py:10-12, 60-62` | Vaza detalhes de implementação |
| LOW | Números mágicos nas regras de desconto | `models.py:256-262` | Regras de negócio sem nome |
| LOW | Imports não usados | `database.py:2`, `models.py:2` | Ruído e falsas dependências |
| LOW | `id` sobrescrevendo builtin; nomes `cursor2/3` | `controllers.py:14, 64, 98` | Leitura mais difícil |

### Projeto 2 — ecommerce-api-legacy (Node.js/Express, 3 arquivos, 180 linhas, 3 endpoints)

Uma God class `AppManager` concentra banco em memória, seed, rotas, regras de checkout e relatório.

| Severidade | Problema | Onde | Por que importa |
|---|---|---|---|
| CRITICAL | Relatório financeiro e exclusão de usuário sem autenticação | `src/AppManager.js:80-84, 131-135`; `src/app.js:5-10` | Qualquer cliente vê o faturamento e apaga usuários |
| CRITICAL | Número completo do cartão e chave do gateway no log | `src/AppManager.js:45` | Dados de pagamento e credenciais em texto puro nos logs |
| CRITICAL | Credenciais fixas no código | `src/utils.js:1-6` | Segredos distribuídos com o código |
| HIGH | God class | `src/AppManager.js:4-138` | Toda mudança atravessa a mesma classe; impossível testar partes isoladas |
| HIGH | Hash de senha caseiro ("badCrypto") com senha padrão | `src/utils.js:17-22`; `src/AppManager.js:68-69` | Hash reversível/fraco e contas criadas com senha conhecida |
| MEDIUM | Checkout sem transação | `src/AppManager.js:50-61` | Falhas no meio deixam usuário, matrícula ou pagamento órfãos |
| MEDIUM | N+1 no relatório financeiro | `src/AppManager.js:83-106` | Uma consulta por curso e por matrícula |
| LOW | Nomes crípticos (`u, e, p, cid, cc`) | `src/AppManager.js:29-33` | Leitura difícil de um fluxo de pagamento |
| LOW | Variável `totalRevenue` morta | `src/utils.js:10, 25` | Código sem efeito que confunde |

### Projeto 3 — task-manager-api (Python/Flask + SQLAlchemy, 15 arquivos, 1158 linhas, 22 endpoints)

Já tem `models/`, `routes/`, `services/` e `utils/`, mas as rotas concentram consultas, regras e transações.

| Severidade | Problema | Onde | Por que importa |
|---|---|---|---|
| CRITICAL | Hash de senha nas respostas JSON | `models/user.py:16-24`; `routes/user_routes.py:33-40, 85-86, 129, 207-210` | Expõe o hash de todos os usuários |
| CRITICAL | Sem autorização; cliente define o próprio `role`; token previsível no login | `routes/user_routes.py:52, 71-78, 119-125, 185-211` | Qualquer um vira admin e altera dados de terceiros |
| CRITICAL | Segredos fixos no código | `app.py:13`; `services/notification_service.py:7-10` | `SECRET_KEY` e credenciais de SMTP no repositório |
| HIGH | MD5 sem salt para senhas | `models/user.py:27-32` | Quebrável com tabelas prontas |
| HIGH | Regra de negócio e persistência nas rotas | `routes/task_routes.py:85-154`; `routes/report_routes.py:12-101` | Rotas "gordas", sem camada de controller/serviço testável |
| MEDIUM | Queries N+1 | `routes/report_routes.py:53-56, 157-164`; `routes/user_routes.py:12-22` | Relatórios fazem uma consulta por usuário/tarefa |
| MEDIUM | Falta de validação de tipos | `routes/task_routes.py:104, 113-114, 260-264`; `routes/report_routes.py:196-202` | Tipos errados viram 500 |
| MEDIUM | CORS aberto para qualquer origem | `app.py:15` | Qualquer site chama a API pelo navegador do usuário |
| LOW | Constantes duplicadas | `utils/helpers.py:110-116` vs. literais nas rotas | Valores de domínio divergem com o tempo |
| LOW | Imports não usados | `app.py:7`; `utils/helpers.py:3-7` | Ruído |
| LOW | APIs deprecated: `Query.get()` (SQLAlchemy 2.x) e `datetime.utcnow()` (Python 3.12+) | `routes/task_routes.py:67, 158`; `routes/user_routes.py:29` | Quebram em versões futuras das bibliotecas |

Os três projetos atendem ao mínimo do enunciado (≥ 5 problemas, com pelo menos 1 CRITICAL/HIGH, 2 MEDIUM e 2 LOW).

---

## B) Construção da Skill

### Estrutura

```text
refactor-arch/
├── SKILL.md                          # orquestração das 3 fases (curto, ~70 linhas)
├── references/
│   ├── project-analysis.md           # Fase 1: heurísticas de detecção e bloco de saída
│   ├── anti-patterns.md              # catálogo AP-01..AP-19 por severidade, com sinais de detecção
│   ├── report-template.md            # template exato do relatório da Fase 2
│   ├── mvc-guidelines.md             # camadas alvo e formas proibidas
│   ├── refactoring-playbook.md       # P-01..P-15: transformações com antes/depois em Python e JS
│   └── validation.md                 # protocolo da Fase 3: contrato, sandbox, gates de aceite
└── scripts/                          # helpers só com a biblioteca padrão do Python (154 testes)
    ├── inventory.py                  # inventário mecânico: stack, versões, arquivos, LOC, endpoints, banco, deprecations
    ├── safe_view.py                  # leitura de código com valores secretos ocultos
    ├── check_report.py               # valida o relatório e a pergunta de aprovação antes de mostrar
    ├── contract.py                   # contrato HTTP: casos, expectativas aprovadas e comparação
    ├── sandbox.py                    # cópias descartáveis, execução isolada e guarda dos dados reais
    ├── check_mvc.py                  # verificação estática das camadas MVC
    └── tests/                        # testes unitários dos helpers
```

O formato Codex tem também `agents/openai.yaml` com `allow_implicit_invocation: false`: a skill só roda quando
invocada explicitamente. No formato Claude, o mesmo efeito vem de `disable-model-invocation: true`.

### Decisões de design

- **SKILL.md curto, conhecimento nas referências.** O SKILL.md só define as fases, a ordem de leitura das
  referências e as regras gerais. O detalhe de cada fase fica no arquivo de referência correspondente, carregado
  apenas quando a fase começa.
- **Toda regra verificável virou script.** Regras só em prosa eram violadas: totais errados, achados não confirmados,
  severidade fora do catálogo, uma causa raiz contada duas vezes, a pergunta de aprovação reescrita. Por isso a Fase 1
  usa os números do `inventory.py`, e a Fase 2 só é mostrada depois que o `check_report.py` imprime `RESULT=ok`. O
  validador confere o template, as linhas citadas, a ordem por severidade, os totais da Fase 1 contra o inventário,
  os IDs do catálogo e a última linha exata `Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]`.
- **Fases 1 e 2 somente leitura.** Nada é criado, executado ou instalado. O código é lido pelo `safe_view.py`, que
  mantém nomes e números de linha mas oculta valores de senhas, chaves e tokens, para que o relatório e os logs do
  agente não repitam segredos.
- **Parada obrigatória.** A Fase 3 só começa com aprovação explícita do usuário ao relatório, e só aplica as
  mudanças de comportamento listadas em `### Alterações de contrato` no relatório aprovado.
- **"Endpoints continuam respondendo" medido, não declarado.** Na Fase 3, o agente grava o contrato HTTP do código
  original em uma cópia descartável com banco novo, deriva as expectativas do candidato a partir das mudanças
  aprovadas e compara (`COMPARE=ok`). O `check_mvc.py` verifica a separação de camadas nos dois sentidos: nada de
  banco em rotas/controllers e nada de objetos HTTP em models/services. Ele também acusa controllers que só repassam
  chamadas e despacho por string. O `sandbox.py` recusa tocar os bancos reais (`DATA_GUARD`).

### Catálogo de anti-patterns (19)

| Severidade | Anti-patterns | Por que estão no catálogo |
|---|---|---|
| CRITICAL | AP-01 credenciais fixas · AP-02 SQL injection · AP-03 endpoints sensíveis sem autenticação · AP-04 exposição de dados sensíveis · AP-05 senha em texto puro/hash fraco · AP-06 God class/God module | Comprometem segurança ou tornam o sistema inviável de evoluir; aparecem nos três projetos |
| HIGH | AP-07 lógica e persistência nas rotas · AP-08 estado global e conexão compartilhada · AP-09 escritas sem transação · AP-10 configuração insegura (debug, bind, CORS) · AP-11 acoplamento sem injeção de dependências | Violações de MVC e de robustez que a Fase 3 precisa corrigir |
| MEDIUM | AP-12 N+1 · AP-13 validação ausente · AP-14 tratamento de erros que vaza detalhes · AP-15 duplicação · AP-16 APIs deprecated | Performance, consistência e manutenção; AP-16 cobre o requisito de APIs obsoletas |
| LOW | AP-17 números/strings mágicos · AP-18 nomes ruins · AP-19 código morto e imports não usados | Legibilidade |

Cada entrada tem sinais de detecção para Python e JavaScript, a severidade padrão e quando ela pode subir ou descer
um nível. O `check_report.py` rejeita severidade fora dessa faixa.

### Como a skill é agnóstica de tecnologia

- A detecção parte de manifestos e imports (`requirements.txt`, `pyproject.toml`, `package.json`), não de nomes de
  projeto. As versões vêm dos metadados instalados (`.venv/*.dist-info`, `node_modules/*/package.json`).
- O catálogo e o playbook descrevem cada problema de forma neutra, com exemplos em Python e em JavaScript.
- As diretrizes MVC mapeiam as mesmas camadas (routes/views, controllers, services, models, middlewares, config)
  para Flask e Express, e dizem como adaptar um projeto que já tem parte das camadas (caso do task-manager).
- Os helpers entendem Python (via `ast`) e JavaScript (análise léxica) e funcionam com qualquer projeto que siga
  esses ecossistemas.

### Desafios e soluções

| Desafio | Solução |
|---|---|
| O modelo relatava totais e versões sem conferir | `inventory.py` como fonte única; `check_report.py` compara os totais da Fase 1 com o inventário |
| Achados genéricos ou sem prova | O template exige arquivo e linhas lidas; o validador recusa linguagem não confirmada ("possível", "pode haver") |
| Segredos aparecendo nos logs ao ler o código | `safe_view.py` oculta valores por nome de variável, argumentos de funções de senha e colunas sensíveis de `INSERT` (inclusive tuplas posicionais do seed). Na 1ª rodada, as senhas do seed do projeto 1 apareceram na saída de uma ferramenta; a regra foi corrigida com teste e a 2ª rodada saiu limpa nos 3 projetos |
| Provar que a refatoração não quebrou endpoints | Contrato HTTP do original em cópias descartáveis e comparação com as mudanças aprovadas (`contract.py` + `sandbox.py`) |
| Não tocar os bancos reais (`loja.db`, `instance/tasks.db`) | Toda execução acontece em cópias sem `*.db`; o `sandbox.py` confere as impressões digitais antes e depois |
| Refatorações "de fachada" (mover arquivos, controllers que só repassam) | `check_mvc.py` verifica dependências entre camadas nos dois sentidos e detecta repasses e despacho por string |
| Subir servidores dentro do sandbox do Codex | A Fase 3 roda com `sandbox_mode="workspace-write"` e `network_access=true`, necessário para abrir portas em loopback |
| A guarda acusava `.aws` e `.codex` como arquivos novos do projeto | O sandbox do Codex monta esses diretórios vazios no diretório de trabalho a cada comando (pontos de montagem, com mtime novo). O `sandbox.py` passou a ignorar pontos de montagem no snapshot (teste novo) |
| O legado do projeto 2 cai com `card` numérico (`TypeError` derruba o processo) e todos os casos seguintes ficavam sem resposta | `contract.py replay --defer/--update-defer`: cada rodada leva para o fim o primeiro caso que derruba o servidor, até não haver mais quedas; esses casos ficam registrados com status 0 e só podem mudar com `expect_status` aprovado no relatório |
| O `check_mvc.py` não reconhecia `rollback()` como acesso ao banco, e a verificação independente achou um middleware fazendo `rollback`/`close` da conexão no projeto 1 | Regra ampliada com teste (`rollback`, `executemany`, `executescript`); o ciclo de vida da conexão foi para `models/connection.py` |
| A ordem dos cursos no relatório do projeto 2 era uma corrida no legado, e a 1ª versão refatorada fixou a ordem minoritária | Sondagem do original (40 chamadas por estado) e alteração de contrato C8, com ordem determinística |

Os helpers foram escritos com TDD (teste falhando antes da implementação) e testados nos três projetos reais antes
de qualquer execução do agente.

---

## C) Resultados

### Relatórios de auditoria (Fase 2)

| Projeto | CRITICAL | HIGH | MEDIUM | LOW | Total | Relatório |
|---|---|---|---|---|---|---|
| code-smells-project | 5 | 5 | 4 | 3 | **17** | [`audit-project-1.md`](reports/audit-project-1.md) |
| ecommerce-api-legacy | 5 | 3 | 3 | 3 | **14** | [`audit-project-2.md`](reports/audit-project-2.md) |
| task-manager-api | 3 | 5 | 5 | 3 | **16** | [`audit-project-3.md`](reports/audit-project-3.md) |

Os achados da análise manual (seção A) aparecem nos três relatórios. Cada relatório termina com a seção
`### Alterações de contrato`: as mudanças de comportamento HTTP que a correção exige (por exemplo, exigir
`X-Admin-Token` nas rotas administrativas, deixar de devolver senhas, responder 400 em vez de 500 para tipos
inválidos). Foram aprovadas como propostas: C1–C10 no projeto 1, C1–C7 no projeto 2 e C1–C7 no projeto 3.

Uma alteração foi acrescentada depois da verificação independente: **C8 no projeto 2**. O relatório financeiro do
legado monta a lista de cursos conforme as consultas assíncronas terminam, então a ordem entre cursos com matrículas é
uma corrida. Com o original rodando, 40 chamadas no mesmo estado deram `Clean Architecture > Docker` 38 vezes e a
ordem inversa 2 vezes. A primeira versão refatorada fixou a ordem minoritária. C8 define a ordem de forma
determinística: cursos sem matrículas primeiro (fato estável do legado) e depois id crescente (a ordem dominante).

### Estrutura antes e depois

**Projeto 1 — code-smells-project** (4 arquivos de código → 43, em camadas)

```text
ANTES                         DEPOIS
app.py        (rotas + SQL)   app.py              # entry point: cria a app via bootstrap
controllers.py                bootstrap.py        # composição: config, banco, middlewares, rotas
models.py                     config/settings.py  # configuração por variáveis de ambiente
database.py                   routes/             # products, users, orders, reports, system
                              controllers/        # fluxo HTTP por recurso
                              validators/         # validação de entrada
                              services/           # regras de negócio (pedido, estoque, relatórios)
                              models/             # SQL parametrizado, conexão, hash de senha
                              middlewares/        # auth (X-Admin-Token), erros, ciclo da conexão
                              constants.py  errors.py  tests/  .env.example
```

**Projeto 2 — ecommerce-api-legacy** (God class `AppManager.js` → 26 arquivos)

```text
ANTES                              DEPOIS
src/app.js                         src/app.js  src/server.js   # composição e inicialização
src/AppManager.js (rotas+SQL+      src/config/index.js         # HOST, PORT, ADMIN_TOKEN, SEED_USER_PASSWORD
                   checkout)       src/routes/                 # checkout, financialReport, user
src/utils.js (config fixa)         src/controllers/            # fluxo HTTP
                                   src/validators/             # checkout, user
                                   src/services/               # checkout em transação, relatório, exclusão em cascata
                                   src/models/                 # db (promises + transação), user, course, enrollment, payment, auditLog
                                   src/middlewares/            # auth, errorHandler, jsonParser
                                   src/errors/  src/constants/  src/utils/password.js  tests/
```

**Projeto 3 — task-manager-api** (camadas parciais → MVC completo)

```text
ANTES                              DEPOIS
app.py  database.py  seed.py       app.py  database.py  seed.py   # mantidos (entry point, extensão, seed)
models/  (classes ORM)             models/        # ORM + consultas (persistence.py)
routes/  (consultas, regras,       routes/        # só registro de rotas (Blueprints)
          validação e commits)     controllers/   # fluxo HTTP por recurso
services/notification_service.py   services/      # regras de task, user, category, report, seed
utils/helpers.py                   validators/    # validação de entrada
                                   middlewares/   # auth, erros, JSON malformado
                                   config/settings.py  constants.py  errors.py  utils/  tests/
```

### Checklist de validação

Os mesmos itens valem para os três projetos; a coluna de evidência indica de onde vem cada marcação.

| Item | P1 | P2 | P3 | Evidência |
|---|---|---|---|---|
| **Fase 1** — Linguagem detectada corretamente | [x] | [x] | [x] | Python 3.14 / JavaScript (Node.js) / Python 3.14 |
| Framework detectado corretamente | [x] | [x] | [x] | Flask 3.1.1 / Express 4.22.1 / Flask 3.0.0 + Flask-SQLAlchemy 3.1.1 |
| Domínio descrito corretamente | [x] | [x] | [x] | e-commerce / LMS com checkout / gerenciador de tarefas |
| Número de arquivos condiz com a realidade | [x] | [x] | [x] | 4 arq. e 780 linhas / 3 e 180 / 15 e 1158, conferidos com a análise manual |
| **Fase 2** — Relatório segue o template | [x] | [x] | [x] | `check_report.py` → `RESULT=ok` |
| Cada finding tem arquivo e linhas exatos | [x] | [x] | [x] | `check_report.py` confere as linhas citadas |
| Findings ordenados por severidade | [x] | [x] | [x] | CRITICAL → LOW |
| Mínimo de 5 findings | [x] | [x] | [x] | 17 / 14 / 16 |
| Detecção de APIs deprecated (se aplicável) | [x] | [x] | [x] | P3: achado 13 (AP-16); P1 e P2: verificado, nenhuma ocorrência |
| Skill pausa e pede confirmação antes da Fase 3 | [x] | [x] | [x] | Última linha: `Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]` |
| **Fase 3** — Estrutura de diretórios segue MVC | [x] | [x] | [x] | `check_mvc.py` → `MVC=ok` e verificação estrutural independente sem violações |
| Configuração extraída (sem hardcoded) | [x] | [x] | [x] | `config/settings.py` / `src/config/index.js` / `config/settings.py`; nenhum segredo do original no código novo |
| Models abstraem os dados | [x] | [x] | [x] | `models/` / `src/models/` / `models/` |
| Views/Routes separadas | [x] | [x] | [x] | `routes/` / `src/routes/` / `routes/` |
| Controllers concentram o fluxo | [x] | [x] | [x] | `controllers/` / `src/controllers/` / `controllers/` |
| Error handling centralizado | [x] | [x] | [x] | `middlewares/error_handler.py` / `src/middlewares/errorHandler.js` / `middlewares/error_handler.py` |
| Entry point claro | [x] | [x] | [x] | `app.py` / `src/app.js` (`npm start`) / `app.py` |
| Aplicação inicia sem erros | [x] | [x] | [x] | logs abaixo |
| Endpoints originais respondem corretamente | [x] | [x] | [x] | contrato comparado com o original: 0 diferenças não aprovadas (tabela abaixo) |

### Validação da Fase 3

Validação feita pela própria skill (resumo final de cada execução):

| Projeto | Contrato | Cobertura | Testes criados | Estrutura |
|---|---|---|---|---|
| code-smells-project | `COMPARE=ok` — 198 casos, 0 não aprovados | 19/19 rotas, 27/27 mensagens de erro | 20 | `MVC=ok` |
| ecommerce-api-legacy | `COMPARE=ok` — 32 casos, 0 não aprovados | 3/3 rotas, sem lacunas | 23 | `MVC=ok` |
| task-manager-api | `COMPARE=ok` — 353 casos, 0 não aprovados | 22/22 rotas, 47/47 mensagens de erro | 18 | `MVC=ok` |

Verificação independente, feita fora da skill com outro conjunto de casos. O código original (commit base) rodou
duas vezes em cópias descartáveis, para separar valores voláteis. O código refatorado rodou com os mesmos casos e
com casos negativos. Cada diferença em relação ao original foi classificada contra o texto das alterações aprovadas,
conferindo também o valor novo da resposta:

| Projeto | Casos | Sem token / token errado → 401 | Sem `ADMIN_TOKEN` configurado → 401 | Diferenças vs. original | Não aprovadas |
|---|---|---|---|---|---|
| code-smells-project | 109/109 | 28/28 | 14/14 | 114 (C1, C2, C4) | **0** |
| ecommerce-api-legacy | 26/26 | 6/6 | 3/3 | 31 (C2, C3, C6 e ids deslocados por C3) | **0** |
| task-manager-api | 200/200 | 42/42 | 21/21 | 259 (C1, C3, C4 e ids deslocados por C4) | **0** |

As suítes dos projetos também passam (20, 23 e 18 testes), e os bancos versionados (`loja.db` e
`instance/tasks.db`) continuam idênticos aos do commit base: toda execução usou cópias.

### Aplicações rodando após a refatoração

Logs gerados subindo cada projeto com o comando original de inicialização numa cópia limpa. As variáveis de ambiente
receberam valores aleatórios gerados na hora, que não aparecem no log. As requisições mostram apenas o status e as
chaves de cada resposta.

<details>
<summary>code-smells-project — <code>python app.py</code></summary>

```text
# code-smells-project — execução após a refatoração
# variáveis definidas (valores gerados na hora, não registrados): SECRET_KEY, ADMIN_TOKEN, SEED_ADMIN_PASSWORD, SEED_JOAO_PASSWORD, SEED_MARIA_PASSWORD
$ .venv/bin/python app.py
[servidor]  * Serving Flask app 'app'
[servidor]  * Debug mode: off
[servidor] [31m[1mWARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.[0m
[servidor]  * Running on http://127.0.0.1:5000
[servidor] [33mPress CTRL+C to quit[0m
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET / HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET /health HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET /produtos HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET /produtos/1 HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "[31m[1mPOST /produtos HTTP/1.1[0m" 401 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "[31m[1mPOST /produtos HTTP/1.1[0m" 400 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "[35m[1mPOST /produtos HTTP/1.1[0m" 201 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "[31m[1mGET /usuarios HTTP/1.1[0m" 401 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET /usuarios HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "[31m[1mPOST /admin/query HTTP/1.1[0m" 403 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:16] "GET /relatorios/vendas HTTP/1.1" 200 -
# requisições
GET /health -> 200 objeto chaves=ambiente,counts,database,status,versao {"status": "ok"}
GET /produtos -> 200 objeto chaves=dados,sucesso
GET /produtos/1 -> 200 objeto chaves=dados,sucesso
POST /produtos -> 401 objeto chaves=erro {"erro": "Não autorizado"}
POST /produtos [X-Admin-Token] -> 400 objeto chaves=erro {"erro": "Estoque é obrigatório"}
POST /produtos [X-Admin-Token] -> 201 objeto chaves=dados,mensagem,sucesso {"mensagem": "Produto criado"}
GET /usuarios -> 401 objeto chaves=erro {"erro": "Não autorizado"}
GET /usuarios [X-Admin-Token] -> 200 objeto chaves=dados,sucesso
POST /admin/query [X-Admin-Token] -> 403 objeto chaves=erro {"erro": "Operação não permitida"}
GET /relatorios/vendas [X-Admin-Token] -> 200 objeto chaves=dados,sucesso
```

</details>

<details>
<summary>ecommerce-api-legacy — <code>node src/app.js</code></summary>

```text
# ecommerce-api-legacy — execução após a refatoração
# variáveis definidas (valores gerados na hora, não registrados): ADMIN_TOKEN, SEED_USER_PASSWORD
$ node src/app.js
[servidor] Frankenstein LMS rodando na porta 3000...
# requisições
POST /api/checkout -> 200 objeto chaves=enrollment_id,msg
POST /api/checkout -> 400 texto 'Bad Request'
GET /api/admin/financial-report -> 401 objeto chaves=error {"error": "Não autorizado"}
GET /api/admin/financial-report [X-Admin-Token] -> 200 lista[2] chaves=course,revenue,students
DELETE /api/users/1 -> 401 objeto chaves=error {"error": "Não autorizado"}
DELETE /api/users/abc [X-Admin-Token] -> 400 objeto chaves=error {"error": "ID inválido"}
```

</details>

<details>
<summary>task-manager-api — <code>python seed.py</code> e <code>python app.py</code></summary>

```text
# task-manager-api — execução após a refatoração
# variáveis definidas (valores gerados na hora, não registrados): SECRET_KEY, ADMIN_TOKEN, SEED_ADMIN_PASSWORD, SEED_USER_PASSWORD, SEED_MANAGER_PASSWORD
$ .venv/bin/python seed.py
Seed concluído com sucesso!
  3 usuários
  4 categorias
  10 tasks
$ .venv/bin/python app.py
[servidor]  * Serving Flask app 'app'
[servidor]  * Debug mode: off
[servidor] [31m[1mWARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.[0m
[servidor]  * Running on http://127.0.0.1:5000
[servidor] [33mPress CTRL+C to quit[0m
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "GET / HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "GET /health HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "GET /tasks HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "[31m[1mPOST /tasks HTTP/1.1[0m" 401 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "[31m[1mPOST /tasks HTTP/1.1[0m" 400 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "[35m[1mPOST /tasks HTTP/1.1[0m" 201 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "[31m[1mGET /users HTTP/1.1[0m" 401 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "GET /users HTTP/1.1" 200 -
[servidor] 127.0.0.1 - - [24/Oct/2026 14:25:18] "GET /reports/summary HTTP/1.1" 200 -
# requisições
GET /health -> 200 objeto chaves=status,timestamp {"status": "ok"}
GET /tasks -> 200 lista[10] chaves=category_id,category_name,created_at,description,due_date,id,overdue,priority,status,tags,title,updated_at,user_id,user_name
POST /tasks -> 401 objeto chaves=error {"error": "Não autorizado"}
POST /tasks [X-Admin-Token] -> 400 objeto chaves=error {"error": "Dados inválidos"}
POST /tasks [X-Admin-Token] -> 201 objeto chaves=category_id,created_at,description,due_date,id,priority,status,tags,title,updated_at,user_id {"status": "pending"}
GET /users -> 401 objeto chaves=error {"error": "Não autorizado"}
GET /users [X-Admin-Token] -> 200 lista[3] chaves=active,created_at,email,id,name,role,task_count
GET /reports/summary [X-Admin-Token] -> 200 objeto chaves=generated_at,overdue,overview,recent_activity,tasks_by_priority,tasks_by_status,user_productivity
```

</details>

### Observações sobre a skill em stacks diferentes

- **Detecção.** As versões vieram dos pacotes instalados (`.venv`, `node_modules`), não só dos manifestos. No projeto
  2, a versão do Node.js não aparece em nenhum arquivo do projeto, e o relatório diz isso em vez de inventar.
- **Monólito × camadas parciais.** Nos projetos 1 e 2, a skill criou todas as camadas. No projeto 3, manteve
  `models/`, `routes/`, `services/` e `seed.py`, acrescentou `controllers/`, `validators/`, `middlewares/` e
  `config/`, e tirou das rotas as consultas, regras e commits.
- **Legado que cai.** O ecommerce original encerra o processo com dados de cartão numéricos (`TypeError` não
  tratado num callback), e todas as requisições seguintes ficavam sem resposta. O protocolo de validação passou a
  executar esses casos por último (`contract.py replay --defer`) e só aceita resposta nova para eles se ela estiver
  aprovada no relatório. No refatorado, esses casos respondem 400.
- **Comportamento assíncrono.** No Express, a ordem do relatório dependia da ordem em que as consultas
  terminavam (C8). No Flask, o comportamento é síncrono, e a única diferença de texto foi a página padrão de JSON
  malformado, que o projeto 3 preserva.
- **Banco.** Os projetos Python usam SQLite em arquivo e foram validados sempre em cópias, sem tocar no banco do
  repositório. O projeto 2 usa SQLite em memória, recriado a cada inicialização, e ganhou transação real no checkout.

---

## D) Como Executar

### Pré-requisitos

- [OpenAI Codex CLI](https://github.com/openai/codex) instalado e autenticado (`codex login`). Foi usada a versão
  0.163.0 com o modelo `gpt-6.1-sol`. Com Claude Code, use a cópia em `.claude/skills/refactor-arch/`.
- Python 3.9+ (os helpers usam só a biblioteca padrão).
- Dependências de cada projeto, para a Fase 3 e para rodar as aplicações:
  - `code-smells-project` e `task-manager-api`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
  - `ecommerce-api-legacy`: `npm install`

### Executar a skill

Fases 1 e 2 (somente leitura); a resposta termina com a pergunta de aprovação:

```bash
cd code-smells-project      # ou ecommerce-api-legacy / task-manager-api
codex exec --sandbox read-only -m gpt-6.1-sol -c model_reasoning_effort="high" \
  '$refactor-arch Execute as Fases 1 e 2 neste projeto. Responda em português do Brasil.'
```

Fase 3, depois de revisar o relatório, retomando a mesma sessão (o `thread_id` aparece no início da saída):

```bash
codex exec resume <thread_id> -m gpt-6.1-sol -c model_reasoning_effort="high" \
  -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' \
  's. Aprovo a Fase 3 com as alterações de contrato propostas no relatório. Não faça commit nem push.'
```

Em modo interativo: `codex`, depois `$refactor-arch`, e responda `s` à pergunta. No Claude Code: `claude "/refactor-arch"`.

### Validar a refatoração

Cada projeto traz testes de regressão criados na Fase 3:

```bash
cd code-smells-project && .venv/bin/python -B -m unittest discover -s tests     # 20 testes
cd task-manager-api   && .venv/bin/python -B -m unittest discover -s tests      # 18 testes
cd ecommerce-api-legacy && node --test tests/                                   # 23 testes
```

Verificação estática das camadas (deve imprimir `MVC=ok`):

```bash
cd code-smells-project    # ou ecommerce-api-legacy / task-manager-api
python3 -I -B .claude/skills/refactor-arch/scripts/check_mvc.py --project-root .
```

Subir a aplicação e conferir manualmente. As variáveis estão em `.env.example` de cada projeto e não são carregadas
automaticamente. Sem `ADMIN_TOKEN`, as rotas administrativas respondem 401.

```bash
cd code-smells-project
export ADMIN_TOKEN=um-token-local SEED_ADMIN_PASSWORD=... SEED_JOAO_PASSWORD=... SEED_MARIA_PASSWORD=...
.venv/bin/python app.py                     # http://127.0.0.1:5000
curl -s http://127.0.0.1:5000/health
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:5000/usuarios
```

Testes dos helpers da skill (em qualquer uma das cópias):

```bash
cd code-smells-project/.agents/skills/refactor-arch/scripts
python3 -I -B -m unittest discover -s tests -t tests
```
