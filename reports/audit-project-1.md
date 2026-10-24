================================
FASE 1: ANÁLISE DO PROJETO
================================
Linguagem:      Python 3.14.4
Framework:      Flask 3.1.1
Dependências:   flask 3.1.1; flask-cors 5.0.1 — versões instaladas iguais às declaradas
Domínio:        API de e-commerce com produtos, usuários, login, pedidos, estoque e relatórios de vendas
Arquitetura:    Monólito com separação parcial em arquivos na raiz. app.py registra rotas e executa SQL administrativo; controllers.py mistura HTTP, validação e consultas; models.py concentra persistência e regras de vários recursos; database.py mantém conexão global e inicializa esquema e dados. Entrada em app.py:6, configuração fixa, inicialização por python app.py.
Arquivos:       4 arquivos de código, 780 linhas
Banco de dados: SQLite (loja.db, caminho relativo) — tabelas: produtos, usuarios, pedidos, itens_pedido; esquema e dados iniciais criados por get_db()
Endpoints:      19
================================

================================
RELATÓRIO DE AUDITORIA ARQUITETURAL
================================
Projeto: code-smells-project
Stack:   Python 3.14.4 + Flask 3.1.1
Arquivos: 4 analisados | 780 linhas de código

## Resumo
CRITICAL: 5 | HIGH: 5 | MEDIUM: 4 | LOW: 3

## Achados

### 1. [CRITICAL] Credenciais e segredos hardcoded (AP-01)
Arquivo: app.py:7; controllers.py:289; database.py:75-82
Descrição: SECRET_KEY e secret_key recebem literais; os usuários iniciais também recebem senhas fixas no código. Os valores foram ocultados pelo visualizador.
Impacto: A distribuição do código distribui também o segredo da aplicação e credenciais de contas iniciais.
Recomendação: Ler SECRET_KEY e credenciais iniciais de variáveis de ambiente, sem valores secretos padrão; usar segredo efêmero quando apropriado e senhas aleatórias não divulgadas para contas iniciais sem configuração. (P-01/P-03)

### 2. [CRITICAL] SQL Injection (AP-02)
Arquivo: models.py:47-50; models.py:57-61; models.py:109-111; models.py:126-129; models.py:139-165; models.py:289-299; app.py:59-78
Descrição: Campos de produtos, usuários, login, busca e itens são concatenados ao SQL. POST /admin/query executa diretamente o SQL recebido. Os conversores inteiros das URLs limitam alguns parâmetros, mas os campos textuais e o corpo das requisições continuam expostos.
Impacto: Entradas podem alterar consultas, contornar o login, acessar dados ou modificar o banco; apóstrofos em textos legítimos também podem quebrar operações.
Recomendação: Parametrizar valores em todas as consultas e desativar a execução de SQL arbitrário com resposta 403. (P-02/P-05)

### 3. [CRITICAL] Endpoints sensíveis sem autenticação/autorização (AP-03)
Arquivo: app.py:11-28; app.py:47-78; controllers.py:167-186; controllers.py:188-255
Descrição: Operações administrativas, alterações de catálogo, consultas de usuários e pedidos, criação de pedidos e relatório financeiro não verificam identidade ou permissão. O login apenas devolve dados do usuário e não estabelece credencial verificada pelas outras rotas.
Impacto: Qualquer cliente pode apagar o banco, modificar estoque e pedidos, consultar dados pessoais e obter faturamento.
Recomendação: Aplicar proteção administrativa explícita às operações listadas em C3, com token de ambiente; manter /admin/query desativado conforme C2. (P-05)

### 4. [CRITICAL] Exposição de dados sensíveis (AP-04)
Arquivo: models.py:72-103; controllers.py:128-144; controllers.py:276-290; app.py:69-73
Descrição: As respostas de consulta de usuários incluem senha; /health divulga secret_key, db_path e debug. A consulta SQL administrativa também devolve linhas sem seleção de campos públicos.
Impacto: Senhas e segredo da aplicação saem do processo por HTTP, permitindo comprometimento de contas e da configuração.
Recomendação: Serializar somente campos públicos, retirar os campos de configuração de /health e bloquear SQL administrativo arbitrário. (P-04/P-05)

### 5. [CRITICAL] Senhas em texto puro (AP-05)
Arquivo: models.py:105-111; models.py:122-130; database.py:75-83
Descrição: Cadastro e dados iniciais gravam a senha diretamente; o login compara o valor recebido ao conteúdo da coluna senha, sem hash.
Impacto: O acesso ao banco ou às respostas atuais de usuários revela credenciais reutilizáveis.
Recomendação: Usar hash adaptativo com salt e verificação segura, incluindo migração de senhas legadas após autenticação válida e hash das novas senhas iniciais. (P-03)

### 6. [HIGH] Módulo centralizador e regras misturadas ao HTTP (AP-06/AP-07)
Arquivo: models.py:1-314; controllers.py:24-96; controllers.py:188-255; controllers.py:264-292; app.py:47-78
Descrição: models.py reúne persistência de vários recursos, cálculo de pedidos e descontos. Controllers concentram validação, notificações e consultas de saúde; app.py executa persistência administrativa. AP-06 está em HIGH porque o módulo centralizador mistura regras e persistência, sem definir rotas.
Impacto: Alterações em recursos independentes atravessam os mesmos módulos; regras e persistência não podem ser verificadas isoladamente do fluxo atual.
Recomendação: Separar modelos por recurso, regras em serviços, validação em validators e fluxo HTTP em controllers, com rotas declarativas. (P-06/P-07)

### 7. [HIGH] Estado global mutável e conexão compartilhada (AP-08)
Arquivo: database.py:4-12; database.py:84-86
Descrição: get_db() reutiliza db_connection global com check_same_thread=False, sem fechamento por requisição.
Impacto: Requisições compartilham o estado da conexão e da transação; uma operação pode interferir em outra.
Recomendação: Usar conexão por contexto de requisição, registrar fechamento no teardown e passar a conexão da operação transacional aos repositórios envolvidos. (P-08)

### 8. [HIGH] Criação de pedido sem proteção transacional completa (AP-09)
Arquivo: models.py:133-169; controllers.py:218-220
Descrição: Existe um único commit final, mas a checagem de estoque ocorre antes das escritas e não há rollback no caminho de falha. Produtos repetidos são validados individualmente contra o mesmo saldo.
Impacto: Concorrência ou repetição de produtos permite ultrapassar o estoque; uma exceção pode deixar escritas pendentes na conexão compartilhada para posterior confirmação.
Recomendação: Iniciar transação antes das verificações, conferir a quantidade acumulada por produto, escrever atomicamente e executar rollback em falhas. (P-09)

### 9. [HIGH] Configuração insegura de execução (AP-10)
Arquivo: app.py:8-9; app.py:88
Descrição: DEBUG está ativo no código e na inicialização; o servidor escuta em todas as interfaces. CORS é habilitado sem restrição explícita de origens em uma API com operações administrativas.
Impacto: O depurador e as operações HTTP ficam expostos na rede; navegadores de origens arbitrárias recebem permissão de acesso pelo CORS.
Recomendação: Configurar debug e endereço por ambiente, com padrões seguros, e usar lista explícita de origens CORS. (P-01/P-12)

### 10. [HIGH] Acoplamento forte sem composição de dependências (AP-11)
Arquivo: app.py:3-6; app.py:82; models.py:1-6; database.py:5-14; database.py:54-84
Descrição: A aplicação é criada no escopo do módulo, os modelos importam diretamente get_db() e a primeira conexão também cria esquema e dados no caminho fixo.
Impacto: Substituir o banco ou exercitar uma regra isolada exige interferir no estado dos módulos e pode inicializar persistência real.
Recomendação: Introduzir create_app(), configuração substituível e composição explícita de repositórios e serviços; preservar a inicialização dos dados no fluxo de execução autorizado. (P-15)

### 11. [MEDIUM] Queries N+1 nas listagens de pedidos (AP-12)
Arquivo: models.py:171-201; models.py:203-233; models.py:139-156
Descrição: Cada pedido dispara busca de itens e cada item dispara busca de produto; a criação também consulta produtos repetidamente.
Impacto: O volume de consultas cresce com pedidos e itens, aumentando o custo das listagens.
Recomendação: Buscar itens e produtos em lote ou com JOIN, preservando a ordem das respostas, os valores e o nome substituto de produtos ausentes. (P-10)

### 12. [MEDIUM] Validação de entrada ausente ou inconsistente (AP-13)
Arquivo: controllers.py:24-54; controllers.py:64-92; controllers.py:111-126; controllers.py:146-174; controllers.py:188-203; controllers.py:237-243; models.py:139-146
Descrição: Não se verifica uniformemente se o JSON é objeto nem os tipos dos campos. Comparações, len(), float() e acesso aos itens podem falhar. Atualização de produto omite verificações de nome e categoria presentes na criação; pedidos não exigem quantidades inteiras positivas.
Impacto: Entradas inválidas geram erros internos ou dados inconsistentes; quantidades negativas podem aumentar estoque e produzir total negativo.
Recomendação: Centralizar validadores por recurso, preservar erros já tratados e definir respostas 400 para as novas rejeições descritas em C4. (P-11)

### 13. [MEDIUM] Tratamento de erros inadequado (AP-14)
Arquivo: controllers.py:5-22; controllers.py:60-62; controllers.py:218-220; controllers.py:291-292; app.py:77-78
Descrição: Blocos de captura genérica repetem respostas com str(e), incluindo detalhes de falhas internas; /health usa detalhes para a mesma exposição.
Impacto: Clientes recebem informações de implementação; a repetição dificulta manter respostas consistentes e distinguir erros esperados.
Recomendação: Centralizar o tratamento, mapear exceções de domínio preservando as respostas previstas e devolver mensagem genérica para falhas inesperadas, sem registrar credenciais. (P-12)

### 14. [MEDIUM] Serialização e montagem de pedidos duplicadas (AP-15)
Arquivo: models.py:12-21; models.py:31-40; models.py:304-313; models.py:178-200; models.py:211-232
Descrição: O mapeamento público de produtos é repetido nas consultas; a montagem de pedidos e itens também é repetida entre as listagens.
Impacto: Uma correção de campo ou formato precisa ser reproduzida em vários locais e pode gerar respostas divergentes.
Recomendação: Extrair serializadores por recurso e reutilizar a montagem dos pedidos com os mesmos campos, tipos e ordenação. (P-14/P-07)

### 15. [LOW] Números e strings de regra sem constantes (AP-17)
Arquivo: models.py:256-262; controllers.py:47-52; controllers.py:242-250
Descrição: Limites e percentuais de desconto, limites de nome, categorias e estados do pedido aparecem como literais nas regras.
Impacto: O significado e a manutenção das regras dependem de localizar e interpretar valores espalhados.
Recomendação: Nomear constantes de domínio e manter seus valores, ordem e critérios de comparação. (P-14)

### 16. [LOW] Nomenclatura pouco expressiva (AP-18)
Arquivo: controllers.py:14; controllers.py:56-58; models.py:24-28; models.py:187-193
Descrição: id oculta o nome de uma função embutida; cursor2, cursor3 e prod dificultam identificar a responsabilidade de cada variável.
Impacto: A leitura do fluxo exige reconstruir o significado dos nomes pelo contexto.
Recomendação: Usar nomes como produto_id e produto, ajustando o vínculo com parâmetros de rota para preservar as URLs. (P-14)

### 17. [LOW] Imports não utilizados (AP-19)
Arquivo: database.py:2; models.py:2
Descrição: os em database.py e sqlite3 em models.py não são referenciados no restante dos respectivos arquivos.
Impacto: Acrescentam ruído e sugerem dependências que esses módulos não utilizam.
Recomendação: Remover os imports sem uso após a reorganização. (P-14)

## Plano proposto e alterações de contrato

### Estrutura alvo

```text
app.py                         # create_app() e inicialização
config/settings.py             # configuração por ambiente
routes/                        # registro de rotas por recurso
controllers/                   # fluxo HTTP por recurso
validators/                    # validação por recurso
services/                      # pedidos, catálogo, usuários e relatórios
models/                        # repositórios e serialização por recurso
models/database.py             # conexão, esquema e dados iniciais
middlewares/auth.py            # proteção administrativa
middlewares/error_handler.py   # mapeamento de erros
errors.py                      # exceções de domínio
constants.py                   # constantes de domínio
```

### Transformações

- Achado 1 -> P-01, P-03: externalizar segredos e credenciais iniciais.
- Achado 2 -> P-02, P-05: parametrizar SQL e desativar consultas arbitrárias.
- Achado 3 -> P-05: aplicar autorização às operações sensíveis.
- Achado 4 -> P-04, P-05: limitar respostas públicas e bloquear acesso SQL direto.
- Achado 5 -> P-03: aplicar hash seguro e migração de senhas legadas.
- Achado 6 -> P-06, P-07: dividir os recursos e separar HTTP, regras e persistência.
- Achado 7 -> P-08: limitar a conexão ao contexto de requisição.
- Achado 8 -> P-09: garantir atomicidade e controle de estoque no pedido.
- Achado 9 -> P-01, P-12: configurar execução e CORS por ambiente.
- Achado 10 -> P-15: compor dependências na fábrica da aplicação.
- Achado 11 -> P-10: carregar pedidos, itens e produtos em lote.
- Achado 12 -> P-11: centralizar validação e respostas para novas rejeições.
- Achado 13 -> P-12: centralizar tratamento sem expor exceções.
- Achado 14 -> P-14, P-07: compartilhar serialização por recurso.
- Achado 15 -> P-14: nomear constantes sem alterar regras.
- Achado 16 -> P-14: tornar nomes expressivos.
- Achado 17 -> P-14: remover imports não utilizados.

### Alterações de contrato

- C1. GET /usuarios; GET /usuarios/<int:id>; GET /health — antes: consultas de usuários incluem senha e a saúde divulga configuração — depois: remover senha dos usuários e secret_key, db_path e debug da saúde; preservar os demais campos e status — motivo: achado 4.
- C2. POST /admin/query — antes: executa SQL e retorna resultados, confirmação ou erro — depois: sempre 403 com JSON {"erro":"Operação não permitida"}, sem acessar o banco — motivo: achados 2, 3 e 4.
- C3. POST /admin/reset-db; POST /produtos; PUT /produtos/<int:id>; DELETE /produtos/<int:id>; GET /usuarios; GET /usuarios/<int:id>; POST /pedidos; GET /pedidos; GET /pedidos/usuario/<int:usuario_id>; PUT /pedidos/<int:pedido_id>/status; GET /relatorios/vendas — antes: acesso sem autorização — depois: exigir X-Admin-Token correspondente à variável ADMIN_TOKEN, sem valor padrão; token ausente ou inválido retorna 401 com JSON {"erro":"Não autorizado"}; sem a variável, todas essas operações permanecem desabilitadas com a mesma resposta. Token válido permite o fluxo original, sujeito às demais mudanças aprovadas. POST /login não passa a emitir esse token; ele é provisionado pelo operador — motivo: achado 3.
- C4. POST /produtos; PUT /produtos/<int:id>; POST /usuarios; POST /login; POST /pedidos; PUT /pedidos/<int:pedido_id>/status; GET /produtos/busca — antes: entradas com tipos inadequados podem gerar 500 ou ser aceitas sem validação suficiente — depois: novas rejeições retornam 400 com JSON {"erro":"Dados inválidos"}. Nos endpoints com corpo, exigir JSON objeto; corpo ausente, JSON malformado ou conteúdo não JSON também retorna 400. Exigir textos nos campos textuais, preço numérico finito, estoque inteiro não negativo e excluir booleanos dos campos numéricos. Aplicar à atualização os limites de nome e categorias já existentes na criação. No cadastro e login, exigir nome quando aplicável, email e senha como textos não vazios. Em pedidos, exigir usuario_id e produto_id inteiros positivos, itens como lista de objetos e quantidade inteira positiva. Na busca, rejeitar limites de preço não numéricos ou não finitos. Erros já tratados mantêm mensagens e precedência; a busca de produto inexistente na atualização continua retornando 404 antes da validação dos campos. Não acrescentar verificação de existência de usuário nem alterar transições de status — motivo: achado 12.
- C5. GET /; GET /produtos; GET /produtos/busca; GET /produtos/<int:id>; POST /produtos; PUT /produtos/<int:id>; DELETE /produtos/<int:id>; GET /usuarios; GET /usuarios/<int:id>; POST /usuarios; POST /login; POST /pedidos; GET /pedidos; GET /pedidos/usuario/<int:usuario_id>; PUT /pedidos/<int:pedido_id>/status; GET /relatorios/vendas; POST /admin/reset-db — antes: falhas inesperadas retornam detalhes de exceções ou página de erro do framework — depois: retornar 500 com JSON {"erro":"Erro interno"}. GET /health mantém 500 e o formato {"status":"erro","detalhes":"Erro interno"} para falhas inesperadas. Erros previstos conservam status e mensagens, exceto C2–C4; páginas HTML de 404/405 permanecem iguais — motivo: achados 4 e 13.
- C6. GET /produtos/busca; POST /produtos; PUT /produtos/<int:id>; POST /usuarios; POST /login; POST /pedidos — antes: entradas podem interferir no SQL ou falhar por conter apóstrofos — depois: tratar valores exclusivamente como dados; textos válidos com apóstrofos passam a funcionar e entradas de injeção deixam de alterar a consulta. No login, credenciais sem correspondência mantêm o 401 existente; tipos inválidos seguem C4 — motivo: achado 2.
- C7. POST /login — antes: novas bases recebem senhas iniciais fixas no código — depois: contas iniciais recebem senhas de SEED_ADMIN_PASSWORD, SEED_JOAO_PASSWORD e SEED_MARIA_PASSWORD; sem a respectiva variável, gerar senha aleatória não divulgada, impedindo login por uma credencial padrão conhecida. Preservar os demais dados iniciais e o formato da resposta do login. Usuários legados continuam autenticando com suas credenciais válidas, migradas para hash após sucesso — motivo: achados 1 e 5.
- C8. POST /pedidos — antes: itens repetidos do mesmo produto são comparados individualmente ao estoque e podem ser aceitos quando a soma excede o saldo — depois: rejeitar esse excesso com 400 e JSON {"erro":"Estoque insuficiente para <nome do produto>","sucesso":false}, sem criar pedido nem alterar estoque. Falhas durante a criação também desfazem todas as escritas; pedidos bem-sucedidos mantêm itens, totais e resposta — motivo: achado 8.
- C9. Processo iniciado por python app.py — antes: debug ativo e endereço 0.0.0.0 — depois: padrão sem debug e endereço 127.0.0.1, configuráveis por FLASK_DEBUG e HOST; preservar porta 5000. As páginas do depurador deixam de ser expostas; falhas HTTP seguem C5 — motivo: achado 9.
- C10. GET /; GET /produtos; GET /produtos/busca; GET /produtos/<int:id>; POST /produtos; PUT /produtos/<int:id>; DELETE /produtos/<int:id>; GET /usuarios; GET /usuarios/<int:id>; POST /usuarios; POST /login; POST /pedidos; GET /pedidos; GET /pedidos/usuario/<int:usuario_id>; PUT /pedidos/<int:pedido_id>/status; GET /relatorios/vendas; GET /health; POST /admin/reset-db; POST /admin/query, incluindo as respectivas requisições OPTIONS — antes: CORS sem restrição explícita de origens — depois: emitir cabeçalhos de autorização CORS somente para origens da lista CORS_ORIGINS; sem configuração, não autorizar origens externas. Preservar os demais aspectos das respostas OPTIONS — motivo: achado 9.

### Preservado

Permanecem os caminhos e métodos inventariados, inclusive /admin/query com o bloqueio explícito de C2, o comando python app.py e a porta 5000. Fora de C1–C10, preservar status, tipos de conteúdo, chaves, tipos e valores JSON, mensagens, ordenação, identificadores e regras de negócio, inclusive descontos e o comportamento atual de cancelamento. Preservar nomes, preços, estoques e demais dados iniciais, exceto a representação e o provisionamento das senhas descritos acima. Não reinicializar nem migrar o banco real durante a auditoria.

### Cobertura

Os quatro arquivos FILE do inventário foram lidos integralmente pelo safe_view.py e confrontados com AP-01 a AP-19; README.md e requirements.txt também foram consultados.
AP-06 e AP-07 foram agrupados pela mesma causa arquitetural; a centralização de regras e persistência justifica HIGH para AP-06.
AP-16: o inventário registrou DEPRECATIONS=0; a leitura não identificou uso das APIs do catálogo que exigisse achado de depreciação.
AP-05: o código demonstra armazenamento e comparação em texto puro; não há chamada de hash nesse fluxo.
Não foram identificados caches globais adicionais, callbacks assíncronos ou imports circulares nos arquivos lidos.
Concorrência, desempenho real, respostas em execução e estado atual dos registros não foram verificados: esta etapa foi exclusivamente estática, sem testes, servidores, instalações ou abertura de bancos.
Nenhum arquivo foi criado, alterado ou excluído. check_report.py validou o texto com RESULT=ok, FINDINGS=17, CRITICAL=5, HIGH=5, MEDIUM=4 e LOW=3; validação funcional e de MVC pertence à Fase 3.

A [skill refactor-arch](../code-smells-project/.claude/skills/refactor-arch/SKILL.md), na Fase 2, exige a pergunta “Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]” e condiciona a próxima fase à aprovação explícita. A execução solicitada das Fases 1 e 2 termina nesta auditoria.

================================
Total: 17 achados
================================

Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]
