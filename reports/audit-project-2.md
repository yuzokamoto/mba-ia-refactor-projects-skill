================================
FASE 1: ANÁLISE DO PROJETO
================================
Linguagem:      JavaScript (Node.js; versão do runtime não identificada pelo inventário)
Framework:      Express 4.22.1 instalado
Dependências:   express 4.22.1 instalado (declarado ^4.18.2); sqlite3 5.1.7 instalado (declarado ^5.1.6)
Domínio:        API de cursos (LMS), com usuários, checkout, matrículas, pagamentos, auditoria e relatório financeiro.
Arquitetura:    Monólito concentrado em AppManager: rotas Express, SQL, regras e validações estão misturados; a configuração está fixa em utils.js. A entrada src/app.js cria o banco, carrega o seed, registra as rotas e inicia o servidor; instalação: npm install; execução: npm start, que chama node src/app.js.
Arquivos:       3 arquivos de código, 180 linhas
Banco de dados: SQLite em memória (:memory:), com seed na inicialização — tabelas: audit_logs, courses, enrollments, payments, users
Endpoints:      3
POST /api/checkout
GET /api/admin/financial-report
DELETE /api/users/:id
================================

================================
RELATÓRIO DE AUDITORIA ARQUITETURAL
================================
Projeto: ecommerce-api-legacy
Stack:   JavaScript / Node.js (versão não identificada) + Express 4.22.1
Arquivos: 3 analisados | 180 linhas de código

## Resumo

CRITICAL: 5 | HIGH: 3 | MEDIUM: 3 | LOW: 3

## Achados

### 1. [CRITICAL] Credenciais e segredos hardcoded (AP-01)

Arquivo: src/utils.js:1-7; src/AppManager.js:18; src/AppManager.js:68
Descrição: dbPass e paymentGatewayKey contêm literais secretos; há senha literal no seed e uma senha padrão literal para novos usuários.
Impacto: Credenciais acompanham o código e podem ser reutilizadas por quem obtiver acesso ao repositório.
Recomendação: Externalizar os segredos para variáveis de ambiente, sem valores secretos padrão, e eliminar a senha padrão do checkout; manter a inicialização possível sem credenciais externas. (P-01)

### 2. [CRITICAL] Endpoints sensíveis sem autenticação/autorização (AP-03)

Arquivo: src/AppManager.js:25-35; src/AppManager.js:40-43; src/AppManager.js:66-80; src/AppManager.js:131-136; src/app.js:5-10
Descrição: Relatório financeiro e exclusão de usuários não verificam o solicitante. O checkout também reutiliza um usuário encontrado pelo e-mail sem verificar sua senha.
Impacto: Terceiros podem consultar informações financeiras, excluir usuários e vincular matrículas a uma identidade alheia.
Recomendação: Aplicar autenticação administrativa por X-Admin-Token nas duas rotas protegidas e verificar a senha ao reutilizar uma conta no checkout, conforme C1 e C2. (P-05, P-03)

### 3. [CRITICAL] Exposição de dados sensíveis em logs (AP-04)

Arquivo: src/AppManager.js:45
Descrição: O console recebe o cartão informado e config.paymentGatewayKey durante o processamento do checkout.
Impacto: Dados de cartão e segredo do gateway ficam acessíveis a leitores e sistemas de coleta dos logs.
Recomendação: Registrar somente o evento e identificadores internos necessários, sem cartão, senha ou chave do gateway. (P-04)

### 4. [CRITICAL] Senhas em texto puro e derivação caseira fraca (AP-05)

Arquivo: src/AppManager.js:18; src/AppManager.js:68-69; src/utils.js:17-22
Descrição: O seed grava uma senha literal em pass. badCrypto repete um fragmento de Base64 e trunca o resultado, sem salt nem derivação de senha adequada.
Impacto: O seed expõe uma senha armazenada e o algoritmo produz colisões e proteção insuficiente para novas contas.
Recomendação: Usar scrypt do módulo crypto, salt aleatório e comparação segura; armazenar somente a derivação da senha, inclusive no seed. (P-03)

### 5. [CRITICAL] God Class e dependências acopladas (AP-06/AP-11)

Arquivo: src/AppManager.js:1-141; src/app.js:5-14
Descrição: AppManager abre sua própria conexão, define schema e seed, registra HTTP, executa SQL, processa pagamentos e monta relatórios. A entrada inicializa banco e servidor imediatamente, sem fábrica de aplicação ou dependências injetadas.
Impacto: Alterações atravessam vários domínios e testar regras isoladamente exige lidar com infraestrutura e efeitos de inicialização.
Recomendação: Separar rotas, controllers, validadores, serviços e models; criar fábrica de aplicação e injetar persistência, configuração e serviços. A lógica extensa nas rotas é absorvida por este achado. (P-06, P-07, P-15)

### 6. [HIGH] Estado global mutável sem ciclo de vida (AP-08)

Arquivo: src/utils.js:9-15; src/utils.js:25; src/AppManager.js:59
Descrição: globalCache é um objeto de módulo exportado e alterado pelos checkouts, sem expiração, limite ou isolamento entre instâncias da aplicação.
Impacto: O estado persiste entre requisições e pode crescer com os usuários, além de interferir no isolamento de testes.
Recomendação: Remover o cache, que não possui leitura no código analisado, e manter apenas um registro de evento sem dados sensíveis. (P-08, P-14)

### 7. [HIGH] Operações relacionadas sem unidade transacional (AP-09)

Arquivo: src/AppManager.js:12-16; src/AppManager.js:43-74; src/AppManager.js:131-136
Descrição: Criação de usuário, matrícula, pagamento e auditoria ocorre em gravações separadas, sem transação ou rollback. A exclusão remove apenas users; o schema não declara chaves estrangeiras para preservar as relações.
Impacto: Falhas podem deixar checkout parcialmente gravado; a exclusão deixa matrículas e pagamentos órfãos, que continuam compondo o relatório.
Recomendação: Coordenar as alterações relacionadas em serviços transacionais, com rollback e isolamento entre checkouts concorrentes; excluir pagamentos e matrículas vinculados antes do usuário, conforme C4 e C6. (P-09, P-07)

### 8. [HIGH] Servidor sem restrição explícita de interface (AP-10)

Arquivo: src/app.js:12-14; src/utils.js:6
Descrição: app.listen recebe apenas a porta, sem host explícito; assim, o servidor não fica restrito ao localhost indicado no README.
Impacto: O serviço pode aceitar conexões pelas interfaces de rede disponíveis no ambiente.
Recomendação: Configurar HOST e PORT por ambiente, mantendo a porta padrão 3000 e adotando 127.0.0.1 como host padrão, conforme C7. (P-01, P-12)

### 9. [MEDIUM] Queries N+1 no relatório financeiro (AP-12)

Arquivo: src/AppManager.js:83-109
Descrição: Após buscar os cursos, o relatório consulta matrículas por curso e executa consultas de usuário e pagamento para cada matrícula; a receita é somada em JavaScript.
Impacto: A quantidade de consultas cresce com cursos e matrículas, aumentando o custo do relatório.
Recomendação: Usar consultas em lote ou joins e agregação adequada, preservando cursos sem matrícula, estudantes, valores e ordem observável da resposta. (P-10)

### 10. [MEDIUM] Validação de entrada incompleta (AP-13)

Arquivo: src/AppManager.js:29-38; src/AppManager.js:46; src/AppManager.js:68-69; src/AppManager.js:131-133
Descrição: O checkout verifica apenas a presença por truthiness de alguns campos; card chega a startsWith sem verificação de tipo, pwd é opcional e o identificador da exclusão vai diretamente ao SQL.
Impacto: Tipos inesperados podem causar exceções assíncronas ou respostas inconsistentes, e identificadores inválidos são aceitos sem um contrato claro.
Recomendação: Criar validadores de corpo, campos e identificadores, preservando os nomes públicos usr, eml, pwd, c_id e card; aplicar C2 e C3. (P-11)

### 11. [MEDIUM] Tratamento de erros incompleto e disperso (AP-14)

Arquivo: src/AppManager.js:37-41; src/AppManager.js:54-60; src/AppManager.js:92-106; src/AppManager.js:131-136
Descrição: Falha ao consultar curso é tratada como curso inexistente; erros de auditoria, consultas internas do relatório e exclusão são ignorados. enrollments.length pode ser acessado após falha da consulta.
Impacto: A API pode informar sucesso após falha, produzir relatório incorreto ou encerrar uma requisição sem resposta controlada.
Recomendação: Propagar erros de persistência para um tratamento central, com mensagens seguras e distinção entre falha de infraestrutura e ausência de recurso, conforme C5. (P-12)

### 12. [LOW] Constantes de negócio repetidas e literais mágicos (AP-15/AP-17)

Arquivo: src/AppManager.js:21; src/AppManager.js:46-48; src/AppManager.js:108
Descrição: O estado PAID aparece no seed, no checkout e no relatório; DENIED e o prefixo de cartão que determina aprovação estão codificados diretamente nas regras.
Impacto: Mudanças no vocabulário de pagamentos ou na simulação exigem alterações em pontos distintos.
Recomendação: Nomear e centralizar os estados e a regra de simulação, mantendo seus valores e o comportamento atual. (P-14)

### 13. [LOW] Nomenclatura pouco expressiva (AP-18)

Arquivo: src/AppManager.js:29-33; src/AppManager.js:52-54; src/AppManager.js:89-106
Descrição: Variáveis internas como u, e, p, cid, cc, c e enr exigem reconstruir o significado pelo contexto.
Impacto: A leitura e a manutenção das regras de checkout e relatório ficam mais sujeitas a enganos.
Recomendação: Usar nomes internos como userName, email, password, courseId, card e enrollment; preservar os nomes dos campos HTTP. (P-14)

### 14. [LOW] Variável e import sem uso funcional (AP-19)

Arquivo: src/utils.js:10; src/utils.js:25; src/AppManager.js:2
Descrição: totalRevenue é declarado, exportado e importado, mas nunca é lido nem atualizado pelo código analisado.
Impacto: A declaração sugere uma responsabilidade inexistente e aumenta o ruído do módulo utilitário.
Recomendação: Remover a variável e suas referências de exportação e importação. (P-14)

## Plano proposto e alterações de contrato

### Estrutura alvo

```text
src/
  app.js                         # fábrica e compatibilidade com node src/app.js
  server.js                      # inicialização e encerramento dos recursos
  config/index.js
  constants/payment.js
  models/
    db.js                        # conexão, schema, seed e transações
    user.model.js
    course.model.js
    enrollment.model.js
    payment.model.js
    auditLog.model.js
  services/
    checkout.service.js
    financialReport.service.js
    user.service.js
  controllers/
    checkout.controller.js
    financialReport.controller.js
    user.controller.js
  routes/
    checkout.routes.js
    financialReport.routes.js
    user.routes.js
  validators/
    checkout.validator.js
    user.validator.js
  middlewares/
    auth.js
    errorHandler.js
  errors/AppError.js
  utils/password.js
```

### Transformações

- Achado 1 -> P-01: externalizar segredos; documentar apenas nomes das variáveis em .env.example, sem valores secretos.
- Achado 2 -> P-05, P-03: proteger administração e exclusão; verificar a senha de usuários existentes no checkout.
- Achado 3 -> P-04: retirar cartão e chave do gateway dos logs.
- Achado 4 -> P-03: substituir badCrypto e a senha em texto puro por scrypt com salt.
- Achado 5 -> P-06, P-07, P-15: distribuir responsabilidades por recurso e compor a aplicação por injeção.
- Achado 6 -> P-08, P-14: remover o cache sem consumidores e seus efeitos globais.
- Achado 7 -> P-09, P-07: aplicar unidade transacional ao checkout e à exclusão dos registros relacionados.
- Achado 8 -> P-01, P-12: configurar host e porta sem alterar a porta padrão.
- Achado 9 -> P-10: eliminar consultas por item, mantendo a representação pública do relatório.
- Achado 10 -> P-11: validar tipos, corpo e identificadores sem renomear campos públicos.
- Achado 11 -> P-12: encaminhar erros de callbacks e manter o mapeamento de respostas aprovadas.
- Achado 12 -> P-14: centralizar constantes de pagamento, sem trocar seus valores.
- Achado 13 -> P-14: esclarecer nomes internos.
- Achado 14 -> P-14: remover totalRevenue.

### Alterações de contrato

- C1. GET /api/admin/financial-report e DELETE /api/users/:id — antes: acesso sem credencial — depois: exigir X-Admin-Token correspondente a ADMIN_TOKEN do ambiente; token ausente, inválido ou variável não configurada retorna 401 JSON {"error":"Não autorizado"}, mantendo as rotas desabilitadas sem configuração; token válido permite o processamento — motivo: achado 2.
- C2. POST /api/checkout — antes: conta existente é reutilizada somente pelo e-mail, e conta nova recebe senha padrão quando pwd está ausente — depois: conta existente exige pwd válido, com 401 JSON {"error":"Credenciais inválidas"} quando ausente ou incorreto; conta nova exige senha não vazia, com 400 e corpo textual "Senha obrigatória" quando ausente ou vazia. A senha do usuário de seed será definida por SEED_USER_PASSWORD; sem essa variável, o checkout desse usuário responderá ao mesmo 401, mantendo o servidor inicializável — motivo: achados 1, 2 e 4.
- C3. POST /api/checkout e DELETE /api/users/:id — antes: tipos e identificadores não têm validação completa, podendo resultar em exceção, 404 ou sucesso indevido — depois: no checkout, corpo que não seja objeto JSON, usr/eml/card que não sejam strings não vazias, pwd informado com tipo diferente de string e c_id que não seja inteiro positivo ou string de dígitos representando inteiro positivo retornam 400 com corpo textual "Bad Request"; os casos já cobertos pela verificação de presença mantêm esse mesmo retorno. Na exclusão, com autenticação válida, id que não represente inteiro positivo retorna 400 JSON {"error":"ID inválido"}. JSON sintaticamente malformado continua sob o tratamento padrão do Express — motivo: achado 10.
- C4. POST /api/checkout, com reflexos em GET /api/admin/financial-report — antes: recusa de pagamento pode deixar usuário recém-criado; falhas posteriores podem deixar matrícula sem pagamento ou checkout sem auditoria — depois: somente concluir o checkout após usuário, matrícula, pagamento e auditoria estarem consistentes; qualquer falha desfaz as gravações da operação, e o relatório não inclui resíduos de checkouts que falharam. Preservar o 400 textual "Pagamento recusado" para a recusa de pagamento — motivo: achado 7.
- C5. POST /api/checkout, GET /api/admin/financial-report e DELETE /api/users/:id — antes: alguns erros de banco são ignorados ou classificados incorretamente — depois: no checkout, erro de consulta de curso retorna 500 textual "Erro DB", em vez de 404 "Curso não encontrado", e falha de auditoria retorna 500 textual "Erro Auditoria", em vez de sucesso; no relatório, erros de qualquer consulta retornam 500 textual "Erro DB"; na exclusão, falha de persistência retorna 500 textual "Erro DB", em vez de sucesso. Erros inesperados das três rotas passam a retornar 500 JSON {"error":"Erro interno"}, sem detalhes internos. Os demais erros já tratados mantêm seus status e corpos — motivo: achado 11.
- C6. DELETE /api/users/:id, com reflexos em GET /api/admin/financial-report — antes: exclui somente o usuário e retorna 200 com a mensagem sobre matrículas e pagamentos deixados no banco — depois: excluir transacionalmente pagamentos e matrículas vinculados e então o usuário; retornar 200 com corpo textual "Usuário deletado". Um id válido inexistente continua respondendo 200 com essa nova mensagem; o relatório deixa de incluir as matrículas e receitas removidas — motivo: achado 7.
- C7. POST /api/checkout, GET /api/admin/financial-report e DELETE /api/users/:id — antes: servidor escuta sem host explícito — depois: usar HOST, com padrão 127.0.0.1, e PORT, com padrão 3000; o acesso por outra interface dependerá da configuração explícita de HOST — motivo: achado 8.

### Preservado

Fora de C1–C7, preservar métodos e caminhos dos endpoints, formatos e tipos das respostas, mensagens, códigos HTTP e comportamento da simulação de pagamento. O checkout bem-sucedido continua retornando 200 JSON com msg e enrollment_id; o relatório mantém course, revenue, students, student e paid, incluindo cursos sem matrículas.

Preservar SQLite em memória, seed automático, identificadores e dados públicos iniciais de usuários, cursos, matrículas e pagamentos; a senha armazenada muda conforme C2. Preservar npm install, npm start, node src/app.js e a porta padrão 3000. Não introduzir integração real de pagamento.

Preservar as respostas padrão do Express para rotas inexistentes, métodos sem rota e erros de parsing de JSON; não converter essas páginas automaticamente para JSON.

### Cobertura

Os três arquivos de código listados pelo inventário foram lidos integralmente com safe_view.py e confrontados com AP-01 a AP-19; package.json, README.md e api.http também foram consultados de forma sanitizada.

AP-02: as consultas que recebem entradas externas usam placeholders; não foi identificada interpolação de entrada em SQL executável.

AP-07: a concentração de regras e persistência nas rotas foi consolidada no achado 5, sem duplicar a causa arquitetural.

AP-15: a duplicação confirmada envolve constantes de pagamento, consolidada com AP-17 no achado 12 e classificada como LOW.

AP-16: o inventário informou DEPRECATIONS=0; não houve linhas DEPRECATED a incluir.

O inventário informou DATA_STORES=0; o código abre SQLite em memória. Nenhum arquivo de banco ou diretório instance foi aberto.

A versão do Node.js, o comportamento sob concorrência e as respostas em execução não foram aferidos. As descrições de comportamento atual decorrem da leitura estática; aplicação, servidor e testes não foram executados, dependências não foram instaladas e arquivos não foram alterados.

A Fase 3 deverá capturar o contrato original em cópias descartáveis e validar somente as alterações aprovadas; os resultados COMPARE, MVC, DATA_GUARD e FINISH ainda não foram obtidos.

A [skill refactor-arch](../ecommerce-api-legacy/.claude/skills/refactor-arch/SKILL.md) determina a pergunta “Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]” e exige aprovação explícita antes da Fase 3. Por isso, esta entrega termina na análise e no plano para revisão.

================================
Total: 14 achados
================================

Fase 2 concluída. Prosseguir com a refatoração (Fase 3)? [s/n]
