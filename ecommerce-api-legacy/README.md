# ecommerce-api-legacy

API de cursos (LMS) em Node.js/Express, com checkout, matrículas, pagamentos e relatório financeiro.
O SQLite funciona em memória e recebe o seed automaticamente a cada inicialização.

## Execução

```bash
npm install
npm start
```

O script de inicialização continua executando o ponto de entrada `src/app.js`.
O endereço padrão é `http://127.0.0.1:3000`.
As dependências existentes são Express e sqlite3; o hash de senhas usa o módulo nativo `crypto`.

Defina as variáveis de ambiente antes de iniciar o processo. `.env.example` lista os nomes sem valores;
o arquivo não é carregado automaticamente.

| Variável | Comportamento |
| --- | --- |
| `HOST` | Interface de rede; padrão `127.0.0.1`. Acesso por outra interface exige configuração explícita. |
| `PORT` | Porta; padrão `3000`. |
| `ADMIN_TOKEN` | Credencial administrativa. Sem ela, relatório e exclusão ficam desabilitados. |
| `SEED_USER_PASSWORD` | Senha da conta inicial, armazenada com scrypt e salt aleatório. Sem ela, o checkout dessa conta fica desabilitado. |

O seed mantém o usuário Leonan, os cursos Clean Architecture e Docker e a matrícula e pagamento iniciais.
Os dados são descartados quando o processo termina. Não há integração com gateway de pagamento:
a simulação aprova strings de cartão iniciadas por `4` e recusa as demais. Não use dados reais de cartão.

## Contrato HTTP

| Método e rota | Uso |
| --- | --- |
| `POST /api/checkout` | Recebe `usr`, `eml`, `pwd`, `c_id` e `card`. |
| `GET /api/admin/financial-report` | Exige o cabeçalho `X-Admin-Token`. |
| `DELETE /api/users/:id` | Exige `X-Admin-Token`; remove também matrículas e pagamentos vinculados. |

O token deve corresponder a `ADMIN_TOKEN`. Credencial ausente ou inválida, inclusive quando a variável
não está configurada, retorna `401` JSON `{"error":"Não autorizado"}`.

No checkout, uma conta existente exige sua senha: ausência ou senha incorreta retorna `401` JSON
`{"error":"Credenciais inválidas"}`. Para uma conta nova, senha ausente ou vazia retorna `400`
com o corpo textual `Senha obrigatória`. `pwd` informado com tipo diferente de string retorna
`400` com `Bad Request`.

O corpo deve ser um objeto JSON. `usr`, `eml` e `card` devem ser strings não vazias;
`c_id` aceita inteiro positivo ou string de dígitos representando inteiro positivo.
Entradas inválidas retornam `400` com o corpo textual `Bad Request`.
Um ID inválido na exclusão retorna `400` JSON `{"error":"ID inválido"}`.

Checkout bem-sucedido retorna `200` JSON com `msg: "Sucesso"` e `enrollment_id`.
Curso inexistente continua retornando `404` com `Curso não encontrado`; pagamento recusado retorna
`400` com `Pagamento recusado`. O checkout é atômico: falhas desfazem todas as suas gravações.

Falhas de persistência retornam `500` com a mensagem textual correspondente: `Erro DB`,
`Erro ao criar usuário`, `Erro Matrícula`, `Erro Pagamento` ou `Erro Auditoria`.
Erros inesperados das rotas retornam `500` JSON `{"error":"Erro interno"}`.
As páginas padrão do Express para URLs sem rota, métodos sem rota e JSON malformado são preservadas.

A exclusão responde `200` com `Usuário deletado`, inclusive para um ID válido inexistente.
O relatório deixa de incluir as matrículas e receitas removidas pela exclusão.

A ordenação aprovada em **C8** é determinística: cursos sem matrículas primeiro, seguidos pelos cursos
com matrículas, com ID crescente dentro de cada grupo. Ela substitui a ordem dependente da conclusão
das consultas assíncronas do legado.

Os exemplos de requisição estão em `api.http` e referenciam credenciais do ambiente.

## Organização

O fluxo é `routes → controllers → services → models`. Validadores cuidam das entradas;
middlewares aplicam autenticação e traduzem erros para HTTP. A fábrica `createApp` recebe
a persistência e a configuração sem abrir conexões ou iniciar o servidor na importação.

As escritas relacionadas usam transações. Uma fila por conexão também coordena as leituras,
impedindo relatórios sobre um checkout parcialmente gravado. O relatório usa consultas em lote
e agregação SQL, sem consultas por aluno.

## Testes

A suíte `tests/ecommerce.test.js` usa `node:test`, SQLite em memória e HTTP local.
Ela verifica autenticação, senhas, validação, rollback, exclusão, concorrência e erros.
Durante o procedimento `refactor-arch`, execute-a somente em cópias descartáveis por
`sandbox.py run`, conforme o protocolo da skill.
