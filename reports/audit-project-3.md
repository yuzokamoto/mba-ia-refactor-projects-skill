================================
FASE 1: ANÁLISE DO PROJETO
================================
Linguagem:      Python 3.14.4
Framework:      Flask 3.0.0
Dependências:   flask 3.0.0; flask-sqlalchemy 3.1.1; flask-cors 4.0.0; marshmallow 3.20.1; requests 2.31.0; python-dotenv 1.0.0 — versões instaladas identificadas pelo inventário.
Domínio:        API de gerenciamento de tarefas, usuários, categorias, autenticação e relatórios de produtividade.
Arquitetura:    Parcialmente organizada em camadas: app.py:9 cria a aplicação e registra Blueprints, mas as rotas concentram consultas ORM, validações, regras e transações. A configuração está no código; a inicialização cria tabelas durante a importação; o serviço de notificações não é chamado pela aplicação. Comandos documentados: python seed.py e python app.py.
Arquivos:       15 arquivos de código, 1158 linhas
Banco de dados: SQLite (URI sqlite:///tasks.db, resolvida pelo Flask-SQLAlchemy em instance/tasks.db) — tabelas: categories, tasks, users; o inventário registra 2 arquivos de armazenamento, não abertos.
Endpoints:      22
================================

================================
RELATÓRIO DE AUDITORIA ARQUITETURAL
================================
Projeto: task-manager-api
Stack:   Python 3.14.4 + Flask 3.0.0
Arquivos: 15 analisados | 1158 linhas de código

## Resumo

CRITICAL: 3 | HIGH: 5 | MEDIUM: 5 | LOW: 3

## Achados

### 1. [CRITICAL] Credenciais e segredos hardcoded (AP-01)

Arquivo: app.py:13; services/notification_service.py:9-10; seed.py:19; seed.py:26; seed.py:33
Descrição: SECRET_KEY, email_password e as senhas passadas a set_password no seed são literais versionados.
Impacto: Quem acessa o código conhece segredos de execução e credenciais iniciais, inclusive de um usuário administrador.
Recomendação: Ler SECRET_KEY e senhas iniciais de variáveis de ambiente, sem valores secretos padrão; remover a credencial SMTP junto do serviço sem utilização. Validar a configuração do seed antes de qualquer escrita. (P-01/P-14)

### 2. [CRITICAL] Endpoints sensíveis sem autenticação/autorização (AP-03)

Arquivo: routes/user_routes.py:42-78; routes/user_routes.py:92-151; routes/user_routes.py:207-211; routes/task_routes.py:225-238; routes/report_routes.py:167-223
Descrição: As rotas permitem criação, edição e exclusão sem verificar o solicitante; role vem do corpo da requisição. O login devolve um token formado por prefixo fixo e identificador, que nenhuma rota verifica.
Impacto: Um cliente anônimo pode criar administradores, alterar contas e excluir usuários com suas tarefas.
Recomendação: Proteger as operações e leituras privadas especificadas em C2 com X-Admin-Token, comparado de forma segura com ADMIN_TOKEN do ambiente; retirar o pseudotoken do login conforme C3. (P-05)

### 3. [CRITICAL] Exposição de dados sensíveis (AP-04)

Arquivo: models/user.py:16-25; routes/user_routes.py:33-40; routes/user_routes.py:85-86; routes/user_routes.py:127-129; routes/user_routes.py:207-211
Descrição: User.to_dict inclui password, contendo o hash da senha. Esse serializador alimenta respostas de consulta, criação, atualização e login.
Impacto: Os hashes saem do processo e permitem tentativas de quebra de senha fora da aplicação.
Recomendação: Excluir password da serialização pública e das respostas indicadas em C1. (P-04)

### 4. [HIGH] Senhas com hash fraco (AP-05)

Arquivo: models/user.py:27-32
Descrição: set_password e check_password utilizam MD5 sem salt.
Impacto: Senhas iguais produzem hashes iguais, e tentativas de quebra são baratas.
Recomendação: Usar hash adaptativo com salt pelo Werkzeug; aceitar o MD5 existente apenas para validar e migrar a senha após um login válido, sem devolvê-lo ao cliente. (P-03)

### 5. [HIGH] Regra de negócio e persistência nas rotas (AP-07)

Arquivo: routes/task_routes.py:85-154; routes/task_routes.py:156-223; routes/user_routes.py:134-151; routes/report_routes.py:15-68; routes/report_routes.py:167-188
Descrição: Handlers validam dados, consultam modelos, calculam regras, alteram entidades, controlam commit/rollback e montam respostas. Categorias também estão misturadas às rotas de relatórios.
Impacto: Regras ficam dependentes do contexto HTTP, e alterações de persistência exigem modificar os handlers.
Recomendação: Separar registro de rotas, controllers HTTP, validators, services por recurso e consultas nos models/repositories; manter transações nos serviços. (P-07)

### 6. [HIGH] Seed com escritas sem transação única (AP-09)

Arquivo: seed.py:11-14; seed.py:16-37; seed.py:39-63; seed.py:78-92
Descrição: A limpeza dos dados, a inclusão de usuários, a inclusão de categorias e a inclusão de tarefas têm commits separados.
Impacto: Uma falha após a limpeza pode deixar dados anteriores apagados e o banco parcialmente repovoado.
Recomendação: Executar limpeza e repovoamento em uma transação, usar flush para obter identificadores intermediários e fazer rollback integral em falhas. (P-09)

### 7. [HIGH] Configuração insegura de execução (AP-10)

Arquivo: app.py:15; app.py:33-34
Descrição: A execução direta habilita debug e escuta em 0.0.0.0; CORS(app) não restringe origens.
Impacto: O servidor de desenvolvimento fica acessível por outras interfaces com depurador habilitado, e navegadores de qualquer origem podem acessar a API.
Recomendação: Externalizar host, debug e origens; usar debug desabilitado, host local e CORS restrito por padrão, mantendo a porta 5000. (P-01/P-12)

### 8. [HIGH] Inicialização acoplada à importação (AP-11)

Arquivo: app.py:9-20; app.py:30-31; seed.py:2
Descrição: Importar app constrói a aplicação e executa create_all; o seed depende dessa instância global.
Impacto: Importar módulos para verificações isoladas pode criar tabelas e exige configuração de banco ativa.
Recomendação: Introduzir create_app com configuração injetável e inicialização explícita do banco; fornecer ao seed uma aplicação criada para sua execução. (P-15)

### 9. [MEDIUM] Queries N+1 e agregações em memória (AP-12)

Arquivo: routes/task_routes.py:14-16; routes/task_routes.py:41-57; routes/user_routes.py:12-22; routes/report_routes.py:53-67; routes/report_routes.py:159-164; routes/task_routes.py:281-287
Descrição: A listagem de tarefas busca usuário e categoria por item; usuários acessam a relação tasks por item; relatórios consultam tarefas por usuário; categorias contam tarefas dentro do laço. Contagens de atrasadas carregam entidades completas.
Impacto: A quantidade de consultas e o consumo de memória crescem com os registros retornados.
Recomendação: Carregar relações em lote e calcular contagens com agregações SQL, preservando ordenação, chaves, arredondamento e critérios atuais. (P-10)

### 10. [MEDIUM] Validação de entrada ausente ou inconsistente (AP-13)

Arquivo: routes/task_routes.py:87-114; routes/task_routes.py:140-144; routes/task_routes.py:260-264; routes/user_routes.py:98-125; routes/user_routes.py:187-201; routes/report_routes.py:169-180; routes/report_routes.py:196-202
Descrição: Não há garantia de corpo JSON como objeto; len, comparações, join, regex e int recebem valores sem checagem de tipo. Atualizações de usuários e categorias validam menos campos que suas criações.
Impacto: Entradas malformadas podem produzir erro interno ou aceitar valores inconsistentes.
Recomendação: Centralizar validações por recurso, verificar tipos antes de operar e converter apenas os casos descritos em C4 para 400 JSON; preservar as mensagens dos erros já tratados. (P-11)

### 11. [MEDIUM] Tratamento de erros inadequado (AP-14)

Arquivo: routes/task_routes.py:62-63; routes/task_routes.py:151-154; routes/task_routes.py:221-223; routes/user_routes.py:130-132; routes/report_routes.py:186-188; routes/report_routes.py:207-209
Descrição: Há capturas genéricas e repetidas; alguns handlers retornam erros sem registrar a causa, e o tratamento varia conforme a operação.
Impacto: Falhas ficam difíceis de diagnosticar e a política de tratamento se dispersa pelas rotas.
Recomendação: Centralizar o mapeamento de exceções de domínio e registrar falhas com dados sensíveis omitidos; preservar respostas atuais, inclusive páginas HTML padrão, salvo C4. (P-12)

### 12. [MEDIUM] Código duplicado (AP-15)

Arquivo: models/task.py:23-36; routes/task_routes.py:17-28; models/task.py:50-60; routes/task_routes.py:30-39; routes/task_routes.py:71-80; routes/user_routes.py:171-180
Descrição: O mapeamento de campos de Task e a regra de atraso aparecem em vários lugares, embora já existam métodos correspondentes no modelo.
Impacto: Uma correção precisa ser repetida e pode deixar respostas divergentes entre endpoints.
Recomendação: Compartilhar a regra de atraso e a serialização base, mantendo projeções específicas de cada endpoint e os campos adicionais atuais. (P-07/P-14)

### 13. [MEDIUM] Uso de APIs deprecated (AP-16)

Arquivo: models/task.py:52; routes/report_routes.py:35; routes/report_routes.py:42; routes/report_routes.py:45; routes/report_routes.py:71; routes/report_routes.py:105; routes/report_routes.py:133; routes/report_routes.py:192; routes/report_routes.py:213; routes/task_routes.py:31; routes/task_routes.py:42; routes/task_routes.py:51; routes/task_routes.py:67; routes/task_routes.py:72; routes/task_routes.py:117; routes/task_routes.py:122; routes/task_routes.py:158; routes/task_routes.py:188; routes/task_routes.py:195; routes/task_routes.py:215; routes/task_routes.py:227; routes/task_routes.py:285; routes/user_routes.py:29; routes/user_routes.py:94; routes/user_routes.py:136; routes/user_routes.py:155; routes/user_routes.py:172; seed.py:66-67; seed.py:69-70; seed.py:74; services/notification_service.py:35; utils/helpers.py:38; models/category.py:11; models/task.py:15-16; models/user.py:14
Descrição: O inventário aponta 34 ocorrências DEPRECATED com status=deprecated: datetime.utcnow e Model.query.get. A leitura também identificou referências a datetime.utcnow em default/onupdate dos modelos, fora dessas ocorrências de chamada.
Impacto: A aplicação utiliza APIs obsoletas nas versões identificadas, aumentando o custo de manutenção e atualização.
Recomendação: Trocar utcnow por um relógio UTC moderno, mantendo valores sem timezone e o formato serializado; substituir Query.get por session.get nas consultas mantidas. (P-13)

### 14. [LOW] Magic numbers / strings (AP-17)

Arquivo: routes/report_routes.py:45-50; routes/report_routes.py:129-130; routes/task_routes.py:110-114; utils/helpers.py:110-116
Descrição: Janela de atividade, limite de alta prioridade, status e limites de validação aparecem como literais locais; parte desses limites já tem constantes no helper sem utilização.
Impacto: Regras ficam pouco explícitas e podem divergir quando alteradas.
Recomendação: Definir constantes nomeadas para regras e domínios, mantendo seus valores atuais e evitando repetir listas locais. (P-14)

### 15. [LOW] Nomenclatura pouco expressiva (AP-18)

Arquivo: routes/report_routes.py:24-28; seed.py:78-89; utils/helpers.py:81-85
Descrição: Nomes como p1 a p5, td e p exigem consultar o contexto para descobrir seu significado.
Impacto: A leitura e a manutenção das regras exigem esforço adicional.
Recomendação: Usar nomes como critical_priority_count, task_data e priority nos trechos mantidos. (P-14)

### 16. [LOW] Código morto e imports não utilizados (AP-19)

Arquivo: app.py:7; models/task.py:3; routes/task_routes.py:7; routes/user_routes.py:6; routes/report_routes.py:7-8; services/notification_service.py:4-48; utils/helpers.py:3-7; utils/helpers.py:57-108
Descrição: Há imports sem uso nos arquivos lidos. NotificationService não é importado nem chamado por nenhum dos arquivos inventariados; process_task_data também não tem chamadas, e os helpers importados pelo relatório não são utilizados.
Impacto: Código sem participação no fluxo aumenta a superfície de manutenção e mantém implementações alternativas de regras.
Recomendação: Remover imports e implementações sem chamadas no projeto, inclusive o serviço de notificações não integrado; manter apenas utilitários efetivamente usados pela nova arquitetura. (P-14)

## Plano proposto e alterações de contrato

### Estrutura alvo

    app.py                         # create_app e composição
    config/settings.py             # ambiente e configuração
    database.py                    # extensão e inicialização explícita
    constants.py
    errors.py                      # exceções de domínio
    routes/                        # registro de método e caminho
        task_routes.py
        user_routes.py
        category_routes.py
        report_routes.py
        system_routes.py
    controllers/                   # fluxo HTTP por recurso
        task_controller.py
        user_controller.py
        category_controller.py
        report_controller.py
        system_controller.py
    validators/                    # corpos e parâmetros por recurso
    services/                      # tarefas, usuários, categorias e relatórios
    models/                        # entidades e consultas/repositories
        task.py
        user.py
        category.py
    middlewares/
        auth.py
        error_handler.py
    seed.py                        # operação transacional explícita

### Transformações

- Achado 1 -> P-01, P-14: externalizar segredos e remover a configuração SMTP sem uso.
- Achado 2 -> P-05: aplicar guarda administrativa às rotas de C2 e retirar o pseudotoken conforme C3.
- Achado 3 -> P-04: omitir password de todas as respostas que hoje usam User.to_dict.
- Achado 4 -> P-03: adotar hash adaptativo e migração no login de registros legados.
- Achado 5 -> P-07: separar rotas, controllers, validação, regras e persistência.
- Achado 6 -> P-09: tornar todo o seed atômico com flush intermediário.
- Achado 7 -> P-01, P-12: configurar execução e CORS com padrões restritos.
- Achado 8 -> P-15: criar fábrica e inicialização explícita sem escrita na importação.
- Achado 9 -> P-10: substituir consultas por item por carregamento em lote e agregações.
- Achado 10 -> P-11: validar formato e tipos nas entradas especificadas em C4.
- Achado 11 -> P-12: centralizar tratamento e diagnóstico, mantendo o contrato residual.
- Achado 12 -> P-07, P-14: compartilhar serialização base e cálculo de atraso.
- Achado 13 -> P-13: modernizar relógio UTC e buscas por chave primária.
- Achado 14 -> P-14: nomear constantes sem mudar seus valores.
- Achado 15 -> P-14: renomear variáveis locais pouco expressivas.
- Achado 16 -> P-14: remover imports e código sem utilização, sem ativar notificações.

### Alterações de contrato

- C1. GET /users/<int:user_id>, POST /users, PUT /users/<int:user_id> e POST /login — antes: respostas de sucesso incluem password no usuário serializado — depois: omitir essa chave, inclusive dentro de user no login — motivo: achado 3.
- C2. POST /tasks, PUT /tasks/<int:task_id>, DELETE /tasks/<int:task_id>, GET /users, GET /users/<int:user_id>, POST /users, PUT /users/<int:user_id>, DELETE /users/<int:user_id>, GET /users/<int:user_id>/tasks, POST /categories, PUT /categories/<int:cat_id>, DELETE /categories/<int:cat_id>, GET /reports/summary e GET /reports/user/<int:user_id> — antes: acesso sem autenticação — depois: exigir X-Admin-Token correspondente a ADMIN_TOKEN do ambiente; ausência, valor incorreto ou variável não configurada retornam 401 JSON {"error":"Não autorizado"}, antes de consultar recursos ou validar o corpo. Sem a variável, essas rotas ficam desabilitadas. Com o token correto, prosseguem com o contrato existente, ressalvadas as demais alterações listadas — motivo: achado 2.
- C3. POST /login — antes: sucesso inclui token previsível sem verificação posterior — depois: omitir token; o login continua validando credenciais e retornando message e user, mas não emite credencial administrativa. ADMIN_TOKEN é provisionado pelo operador e nunca devolvido pelo login — motivo: achado 2.
- C4. POST /tasks, PUT /tasks/<int:task_id>, POST /users, PUT /users/<int:user_id>, POST /categories, PUT /categories/<int:cat_id> e POST /login — antes: corpos JSON de tipo inadequado e valores incompatíveis com operações de texto, comparação, regex, join ou persistência podem causar 500 ou aceitação inconsistente — depois: responder 400 JSON {"error":"Dados inválidos"} para esses novos casos, verificando objeto JSON e tipos dos campos fornecidos: textos como strings, priority e identificadores como inteiros sem booleanos, active como booleano e tags como string, lista de strings ou null. Manter a aceitação atual de null nos campos opcionais que a comportam, de campos desconhecidos e dos erros já tratados; manter também a precedência atual de 404 quando a atualização procura primeiro o recurso. GET /tasks/search — antes: priority ou user_id não conversíveis por int causam falha — depois: responder 400 com o mesmo JSON. JSON sintaticamente inválido e Content-Type incompatível mantêm as respostas padrão do Flask — motivo: achado 10.
- C5. Todas as rotas inventariadas, inclusive respostas automáticas OPTIONS — antes: CORS permite qualquer origem — depois: origens permitidas vêm de CORS_ORIGINS; sem configuração, não enviar autorização CORS. Corpos e status permanecem, com alteração dos cabeçalhos CORS conforme a origem — motivo: achado 7.
- C6. Execução por python app.py — antes: debug habilitado e escuta em todas as interfaces — depois: debug desabilitado e escuta em 127.0.0.1 por padrão; HOST e FLASK_DEBUG permitem configuração explícita, mantendo a porta 5000. Erros inesperados antes renderizados pelo depurador passam à página HTML 500 padrão; erros JSON já tratados e páginas HTML 404/405 permanecem — motivo: achado 7.
- C7. Seed e logins POST /login dos usuários iniciais — antes: senhas iniciais fixas no código — depois: obtê-las de SEED_ADMIN_PASSWORD, SEED_USER_PASSWORD e SEED_MANAGER_PASSWORD; ausência de qualquer uma interrompe o seed antes de alterar dados. As credenciais válidas após novo seed passam a ser as configuradas; bancos existentes continuam aceitando suas credenciais e migram o hash após login válido. Preservar os demais dados iniciais — motivo: achados 1 e 4.

### Preservado

Fora de C1–C7, manter caminhos, métodos, códigos HTTP, tipos de conteúdo, chaves e tipos JSON, mensagens, ordenação e projeções específicas de cada resposta. Preservar o formato de datas sem timezone, os critérios de atraso, as taxas arredondadas e os retornos para listas vazias.
Manter os usuários, categorias, tarefas, relações e identificadores do seed, exceto credenciais e representação interna do hash explicitadas acima. Manter python seed.py e python app.py, com as novas configurações documentadas.
A refatoração futura deverá comparar o contrato original em cópias descartáveis, aplicar somente as exceções aprovadas e concluir os validadores de contrato, MVC e proteção dos dados.

### Cobertura

Todos os 15 arquivos FILE do inventário foram lidos com safe_view.py e examinados contra AP-01 a AP-19.
AP-02: não foi encontrada montagem de SQL textual com entrada externa; as expressões like com f-string usam a API de expressões do ORM.
AP-06: não foi identificado módulo que reúna o critério de múltiplos domínios do catálogo; a concentração nos handlers foi registrada em AP-07.
AP-08: não foi encontrada conexão bruta ou coleção global mutável usada por requisições; db é uma extensão SQLAlchemy, e notifications pertence a instâncias de um serviço não integrado.
AP-09: a exclusão de usuário e de suas tarefas usa um único commit; o problema confirmado está no seed.
AP-16: todas as 34 linhas DEPRECATED do inventário foram contempladas no achado 13; referências adicionais do relógio nos defaults foram identificadas na leitura.
Limites: auditoria estática; código da aplicação, testes, servidor e SMTP não foram executados. Os arquivos de armazenamento e instance/ não foram abertos. Não houve criação, edição ou exclusão de arquivos.
A pausa segue a [SKILL.md](../task-manager-api/.claude/skills/refactor-arch/SKILL.md), que exige a pergunta “Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]” e aprovação explícita antes da Fase 3.

================================
Total: 16 achados
================================

Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]
