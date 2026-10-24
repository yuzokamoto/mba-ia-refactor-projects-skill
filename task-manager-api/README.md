# task-manager-api

API de gerenciamento de tarefas em Flask, organizada em MVC.

O fluxo é rotas → controllers → validators/services → models/repositories.
As rotas registram os endpoints; os controllers cuidam de HTTP; os serviços
coordenam regras e transações; os modelos executam consultas e persistência.
Importar a aplicação não cria tabelas. A fábrica `create_app(settings)` aceita
configuração explícita para execução isolada.

## Execução

As dependências continuam declaradas em `requirements.txt`. Os comandos são:

```bash
python seed.py
python app.py
```

Configure as variáveis no ambiente do processo antes de executar os comandos.
O arquivo `.env.example` lista somente seus nomes; ele não é carregado
automaticamente. Variáveis opcionais podem ser omitidas.

| Variável | Comportamento |
| --- | --- |
| SECRET_KEY | Segredo da aplicação; quando ausente, gera um valor efêmero aleatório. |
| ADMIN_TOKEN | Credencial administrativa; as operações protegidas ficam desabilitadas quando ausente ou vazia. |
| SEED_ADMIN_PASSWORD | Senha inicial do administrador, obrigatória para executar o seed. |
| SEED_USER_PASSWORD | Senha inicial do usuário comum, obrigatória para executar o seed. |
| SEED_MANAGER_PASSWORD | Senha inicial do gerente, obrigatória para executar o seed. |
| DATABASE_URL | URI SQLAlchemy; padrão `sqlite:///tasks.db`, em `instance/tasks.db`. |
| HOST | Interface de escuta; padrão `127.0.0.1`. |
| FLASK_DEBUG | Habilita debug somente quando igual a `1`; desabilitado por padrão. |
| CORS_ORIGINS | Origens permitidas separadas por vírgula; sem configuração, não autoriza CORS. |

A porta permanece 5000. O seed substitui usuários, categorias e tarefas em uma
única transação e verifica todas as senhas antes de acessar o banco. A ausência de
credenciais interrompe a operação; uma falha durante o repovoamento reverte as
escritas. Os demais dados iniciais e relacionamentos foram preservados.

## Autorização e contrato

Envie `X-Admin-Token` com o valor provisionado em `ADMIN_TOKEN` para:

- criar, atualizar ou excluir tarefas;
- listar, consultar, criar, atualizar ou excluir usuários e consultar suas tarefas;
- criar, atualizar ou excluir categorias;
- consultar os relatórios geral e por usuário.

A ausência ou divergência da credencial responde 401 com
`{"error":"Não autorizado"}`, antes de validar o corpo ou procurar recursos.
`GET /tasks`, `GET /tasks/<id>`, `GET /tasks/search`, `GET /tasks/stats`,
`GET /categories`, `GET /`, `GET /health` e `POST /login` continuam públicos.
OPTIONS permanece disponível para preflight, sujeito à configuração de CORS.

O login valida credenciais e devolve `message` e `user`. Ele não emite token
administrativo. Respostas de usuário não incluem senhas ou hashes. Novas senhas
usam hash adaptativo com salt; registros MD5 existentes são migrados somente
após um login válido de usuário ativo, sem migração automática dos bancos.

Corpos JSON incompatíveis e tipos inválidos que antes causavam erro interno ou
eram aceitos indevidamente respondem 400 com `{"error":"Dados inválidos"}`.
Mensagens de negócio já tratadas continuam iguais, assim como as páginas HTML
de JSON malformado, tipo de conteúdo incompatível, 404 e 405. Atualizações
continuam procurando o recurso antes de analisar o corpo. Datas mantêm o formato
sem timezone e estatísticas mantêm os tipos e arredondamentos anteriores.

O serviço de notificações sem integração e os helpers sem uso foram removidos;
nenhum envio de email é executado pela API.

## Verificação isolada

A suíte `tests/test_refactor.py` usa bancos SQLite em memória e cobre autorização,
CORS, validação, respostas públicas, migração de hashes, rollback do seed e número
de consultas conforme os dados crescem. Execute-a somente em uma cópia
descartável, conforme o protocolo da skill refactor-arch:

```bash
python -B -m unittest discover -s tests -v
```
