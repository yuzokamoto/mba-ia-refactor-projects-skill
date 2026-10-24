# code-smells-project

API de E-commerce em Python/Flask usada como entrada do desafio `refactor-arch`.

## Como rodar

```bash
pip install -r requirements.txt
python app.py
```

A aplicação sobe em `http://localhost:5000`. O banco SQLite (`loja.db`) é criado automaticamente no primeiro boot, já com produtos e usuários de exemplo.

## Configuração após a refatoração

As variáveis listadas em `.env.example` devem ser exportadas no ambiente; esse
arquivo não é carregado automaticamente. Nenhuma dependência adicional é necessária.

- `SECRET_KEY`: segredo da aplicação. Sem configuração, uma chave efêmera é gerada.
- `ADMIN_TOKEN`: habilita as operações protegidas com o cabeçalho `X-Admin-Token`.
  Sem essa variável, essas operações retornam 401. O login não emite esse token.
- `SEED_ADMIN_PASSWORD`, `SEED_JOAO_PASSWORD`, `SEED_MARIA_PASSWORD`: senhas das
  contas iniciais de uma nova base. Sem a variável correspondente, a conta recebe
  senha aleatória não divulgada. Senhas existentes são preservadas e convertidas
  para hash após autenticação válida.
- `DATABASE_PATH`: caminho do banco; padrão `loja.db`.
- `HOST`: endereço de escuta; padrão `127.0.0.1`. A porta continua sendo 5000.
- `FLASK_DEBUG`: somente o valor `1` habilita debug; o padrão é desabilitado.
- `CORS_ORIGINS`: origens autorizadas, separadas por vírgula. Sem configuração,
  origens externas não recebem autorização CORS. Use origens completas explícitas.

Produtos podem ser consultados publicamente. Alterar o catálogo, consultar
usuários, criar e consultar pedidos, alterar status, consultar o relatório e
resetar o banco exige o token administrativo. Cadastro e login continuam públicos.
`POST /admin/query` sempre retorna 403 e não executa consultas.

## Organização

`app.py` fornece `create_app(settings=None, database=None)`. `bootstrap.py` compõe
as dependências; `routes/` registra os caminhos; `controllers/` trata HTTP;
`validators/` valida entradas; `services/` aplica regras; `models/` contém
persistência e serialização; `middlewares/` concentra autorização e erros.
Pedidos usam transação com bloqueio antes da leitura do estoque e rollback em
falhas. Conexões são abertas por contexto e fechadas ao final de cada requisição.
`models/connection.py` gerencia abertura, rollback e fechamento; o middleware
apenas registra o gancho de encerramento do contexto Flask.

Os testes de regressão estão em `tests/`. Na execução da skill, aplicação e testes
rodam exclusivamente em cópias descartáveis, sem abrir o banco do projeto.
