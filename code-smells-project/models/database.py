import secrets
import sqlite3

from models.passwords import hash_password


PRODUCT_SEEDS = (
    ("Notebook Gamer", "Notebook potente para jogos", 5999.99, 10, "informatica"),
    ("Mouse Wireless", "Mouse sem fio ergonômico", 89.90, 50, "informatica"),
    ("Teclado Mecânico", "Teclado mecânico RGB", 299.90, 30, "informatica"),
    ("Monitor 27''", "Monitor 27 polegadas 144hz", 1899.90, 15, "informatica"),
    ("Headset Gamer", "Headset com microfone", 199.90, 25, "informatica"),
    ("Cadeira Gamer", "Cadeira ergonômica", 1299.90, 8, "moveis"),
    ("Webcam HD", "Webcam 1080p", 249.90, 20, "informatica"),
    ("Hub USB", "Hub USB 3.0 7 portas", 79.90, 40, "informatica"),
    ("SSD 1TB", "SSD NVMe 1TB", 449.90, 35, "informatica"),
    ("Camiseta Dev", "Camiseta estampa código", 59.90, 100, "vestuario"),
)
USER_SEEDS = (
    ("Admin", "admin@loja.com", "admin", "admin"),
    ("João Silva", "joao@email.com", "cliente", "joao"),
    ("Maria Santos", "maria@email.com", "cliente", "maria"),
)
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, descricao TEXT,
        preco REAL, estoque INTEGER, categoria TEXT, ativo INTEGER DEFAULT 1,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, email TEXT, senha TEXT,
        tipo TEXT DEFAULT 'cliente', criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER,
        status TEXT DEFAULT 'pendente', total REAL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS itens_pedido (
        id INTEGER PRIMARY KEY AUTOINCREMENT, pedido_id INTEGER, produto_id INTEGER,
        quantidade INTEGER, preco_unitario REAL)""",
)


class Database:
    def __init__(self, path, seed_passwords):
        self.path = path
        self.seed_passwords = seed_passwords

    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        connection = self.connect()
        try:
            with connection:
                for statement in SCHEMA:
                    connection.execute(statement)
                if connection.execute("SELECT COUNT(*) FROM produtos").fetchone()[0] == 0:
                    connection.executemany(
                        "INSERT INTO produtos (nome, descricao, preco, estoque, categoria) VALUES (?, ?, ?, ?, ?)",
                        PRODUCT_SEEDS,
                    )
                    connection.executemany(
                        "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                        [(name, email, hash_password(self.seed_passwords.get(key) or
                          secrets.token_urlsafe(32)), role)
                         for name, email, role, key in USER_SEEDS],
                    )
        finally:
            connection.close()
