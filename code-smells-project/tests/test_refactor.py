import os
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import create_app
from config.settings import Settings
from models.database import Database
from models.orders import OrderRepository
from models.passwords import verify_password
from models.products import ProductRepository


class RefactorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.password = secrets.token_urlsafe(24)
        self.admin = secrets.token_urlsafe(24)
        self.database = Database(str(Path(self.directory.name) / "isolado.db"),
                                 {"admin": self.password})
        self.app = create_app({
            "TESTING": True, "DEBUG": False,
            "ADMIN_TOKEN": self.admin, "CORS_ORIGINS": [],
        }, database=self.database)
        self.client = self.app.test_client()
        self.headers = {"X-Admin-Token": self.admin}

    def snapshot(self):
        connection = self.database.connect()
        try:
            return (
                tuple(tuple(row) for row in connection.execute("SELECT id, estoque FROM produtos ORDER BY id")),
                connection.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM itens_pedido").fetchone()[0],
            )
        finally:
            connection.close()

    def test_defaults_and_environment_are_evaluated_per_factory(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.load()
            self.assertFalse(settings["DEBUG"])
            self.assertEqual(settings["HOST"], "127.0.0.1")
            self.assertEqual(settings["DATABASE_PATH"], "loja.db")
            self.assertEqual(settings["CORS_ORIGINS"], [])
            self.assertIsNone(settings["ADMIN_TOKEN"])
            self.assertNotEqual(settings["SECRET_KEY"], Settings.load()["SECRET_KEY"])
        with patch.dict(os.environ, {"HOST": "0.0.0.0", "FLASK_DEBUG": "1",
                                     "CORS_ORIGINS": "https://a.example, https://b.example"}):
            settings = Settings.load()
            self.assertTrue(settings["DEBUG"])
            self.assertEqual(settings["HOST"], "0.0.0.0")
            self.assertEqual(len(settings["CORS_ORIGINS"]), 2)

    def test_seed_login_and_public_serialization(self):
        login = self.client.post("/login", json={"email": "admin@loja.com", "senha": self.password})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(set(login.json["dados"]), {"id", "nome", "email", "tipo"})
        users = self.client.get("/usuarios", headers=self.headers)
        self.assertEqual(len(users.json["dados"]), 3)
        for user in users.json["dados"]:
            self.assertNotIn("senha", user)
        health = self.client.get("/health")
        self.assertEqual(set(health.json), {"status", "database", "counts", "versao", "ambiente"})
        self.assertEqual(health.json["counts"], {"produtos": 10, "usuarios": 3, "pedidos": 0})

    def test_password_hash_and_legacy_migration(self):
        connection = self.database.connect()
        try:
            stored = connection.execute("SELECT senha FROM usuarios WHERE id = 1").fetchone()[0]
            valid, legacy = verify_password(stored, self.password)
            self.assertTrue(valid)
            self.assertFalse(legacy)
            raw = secrets.token_urlsafe(24)
            with connection:
                connection.execute("UPDATE usuarios SET senha = ? WHERE id = 1", (raw,))
            failed = self.client.post("/login", json={"email": "admin@loja.com", "senha": "incorreta"})
            self.assertEqual(failed.status_code, 401)
            self.assertTrue(connection.execute("SELECT senha FROM usuarios WHERE id = 1").fetchone()[0] == raw)
            response = self.client.post("/login", json={"email": "admin@loja.com", "senha": raw})
            self.assertEqual(response.status_code, 200)
            migrated = connection.execute("SELECT senha FROM usuarios WHERE id = 1").fetchone()[0]
            valid, legacy = verify_password(migrated, raw)
            self.assertTrue(valid)
            self.assertFalse(legacy)
        finally:
            connection.close()

    def test_unconfigured_seed_passwords_are_distinct_hashes(self):
        connection = self.database.connect()
        try:
            rows = connection.execute("SELECT senha FROM usuarios WHERE id IN (2, 3)").fetchall()
            self.assertTrue(all(row[0].startswith("scrypt:") for row in rows))
            self.assertNotEqual(rows[0][0], rows[1][0])
        finally:
            connection.close()

    def test_authentication_fails_closed_for_unconfigured_token(self):
        self.app.config["ADMIN_TOKEN"] = None
        for method, path in [("POST", "/admin/reset-db"), ("POST", "/produtos"),
                             ("PUT", "/produtos/1"), ("DELETE", "/produtos/1"),
                             ("GET", "/usuarios"), ("GET", "/usuarios/1"),
                             ("POST", "/pedidos"), ("GET", "/pedidos"),
                             ("GET", "/pedidos/usuario/1"), ("PUT", "/pedidos/1/status"),
                             ("GET", "/relatorios/vendas")]:
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method, headers=self.headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json, {"erro": "Não autorizado"})

    def test_blocked_query_never_opens_a_connection(self):
        with patch.object(self.database, "connect", side_effect=AssertionError("acesso indevido")):
            for kwargs in ({}, {"json": {"sql": "SELECT 1"}},
                           {"data": '{"', "content_type": "application/json"}):
                response = self.client.post("/admin/query", **kwargs)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json, {"erro": "Operação não permitida"})

    def test_cors_exact_origin_and_preflight(self):
        origin = "https://cliente.example"
        self.assertNotIn("Access-Control-Allow-Origin",
                         self.client.get("/", headers={"Origin": origin}).headers)
        app = create_app({"ADMIN_TOKEN": self.admin, "CORS_ORIGINS": [origin]}, database=self.database)
        client = app.test_client()
        for path in ("/", "/produtos", "/usuarios", "/pedidos", "/health", "/admin/query"):
            with self.subTest(path=path):
                response = client.options(path, headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "X-Admin-Token,Content-Type"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
                rejected = client.options(path, headers={"Origin": "https://intruso.example"})
                self.assertNotIn("Access-Control-Allow-Origin", rejected.headers)

    def test_framework_pages_remain_html(self):
        for path, method, status in [("/ausente", "GET", 404), ("/", "PATCH", 405),
                                     ("/produtos/nao-inteiro", "GET", 404)]:
            response = self.client.open(path, method=method)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.mimetype, "text/html")

    def test_malformed_and_non_json_are_rejected(self):
        for path, method in [("/produtos", "POST"), ("/produtos/1", "PUT"),
                             ("/usuarios", "POST"), ("/login", "POST"),
                             ("/pedidos", "POST"), ("/pedidos/1/status", "PUT")]:
            for body, content_type in [('{"', "application/json"), ("texto", "text/plain")]:
                with self.subTest(path=path, content_type=content_type):
                    response = self.client.open(path, method=method, data=body,
                                                content_type=content_type, headers=self.headers)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json, {"erro": "Dados inválidos"})

    def test_injection_and_apostrophes(self):
        name = "Produto d'água"
        response = self.client.post("/produtos", headers=self.headers,
                                    json={"nome": name, "preco": 2.5, "estoque": 3})
        self.assertEqual(response.status_code, 201)
        product_id = response.json["dados"]["id"]
        self.assertEqual(self.client.get("/produtos/" + str(product_id)).json["dados"]["nome"], name)
        self.assertEqual(self.client.get("/produtos/busca", query_string={"q": "d'água"}).json["total"], 1)
        self.assertEqual(self.client.get("/produtos/busca", query_string={"q": "' OR 1=1 --"}).json["total"], 0)
        self.assertEqual(self.client.post("/login", json={
            "email": "' OR 1=1 --", "senha": "incorreta"}).status_code, 401)
        email = "o'connor@example.test"
        response = self.client.post("/usuarios", json={"nome": "O'Connor", "email": email,
                                                       "senha": self.password})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post("/login", json={"email": email,
                                                         "senha": self.password}).status_code, 200)

    def test_invalid_order_quantities_and_duplicate_stock(self):
        before = self.snapshot()
        for quantity in (True, 0, -1, 1.5, "1", None):
            response = self.client.post("/pedidos", headers=self.headers, json={
                "usuario_id": 1, "itens": [{"produto_id": 2, "quantidade": quantity}]})
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/pedidos", headers=self.headers, json={
            "usuario_id": 1, "itens": [{"produto_id": 2, "quantidade": 30},
                                     {"produto_id": 2, "quantidade": 30}]})
        self.assertEqual(response.json, {"erro": "Estoque insuficiente para Mouse Wireless", "sucesso": False})
        self.assertEqual(self.snapshot(), before)

    def test_mid_write_failure_rolls_back_and_hides_details(self):
        before = self.snapshot()
        original = OrderRepository.insert_item
        calls = []
        def fail_second(repository, *args):
            calls.append(None)
            if len(calls) == 2:
                raise RuntimeError("detalhe privado")
            return original(repository, *args)
        with patch.object(OrderRepository, "insert_item", fail_second):
            response = self.client.post("/pedidos", headers=self.headers, json={
                "usuario_id": 1, "itens": [{"produto_id": 2, "quantidade": 1},
                                         {"produto_id": 3, "quantidade": 1}]})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"erro": "Erro interno"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.post("/pedidos", headers=self.headers, json={
            "usuario_id": 1, "itens": [{"produto_id": 2, "quantidade": 1}]}).status_code, 201)

    def test_concurrent_orders_cannot_oversell(self):
        def order(_):
            with self.app.test_client() as client:
                return client.post("/pedidos", headers=self.headers, json={
                    "usuario_id": 1, "itens": [{"produto_id": 1, "quantidade": 6}]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(order, range(2)))
        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(self.client.get("/produtos/1").json["dados"]["estoque"], 4)
        self.assertEqual(len(self.client.get("/pedidos", headers=self.headers).json["dados"]), 1)

    def test_order_listing_uses_two_queries_and_preserves_items(self):
        for _ in range(3):
            self.assertEqual(self.client.post("/pedidos", headers=self.headers, json={
                "usuario_id": 1, "itens": [{"produto_id": 2, "quantidade": 1},
                                         {"produto_id": 3, "quantidade": 1}]}).status_code, 201)
        statements = []
        original = self.database.connect
        def traced_connection():
            connection = original()
            connection.set_trace_callback(statements.append)
            return connection
        with patch.object(self.database, "connect", traced_connection):
            response = self.client.get("/pedidos", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["dados"]), 3)
        self.assertTrue(all(len(order["itens"]) == 2 for order in response.json["dados"]))
        self.assertEqual(sum(statement.startswith("SELECT") for statement in statements), 2)

    def test_cancel_and_missing_user_behavior_is_preserved(self):
        response = self.client.post("/pedidos", headers=self.headers, json={
            "usuario_id": 999999, "itens": [{"produto_id": 2, "quantidade": 1}]})
        self.assertEqual(response.status_code, 201)
        stock = self.client.get("/produtos/2").json["dados"]["estoque"]
        order_id = response.json["dados"]["pedido_id"]
        self.assertEqual(self.client.put("/pedidos/" + str(order_id) + "/status",
            headers=self.headers, json={"status": "cancelado"}).status_code, 200)
        self.assertEqual(self.client.get("/produtos/2").json["dados"]["estoque"], stock)
        self.assertEqual(self.client.put("/pedidos/999999/status", headers=self.headers,
                                        json={"status": "entregue"}).status_code, 200)

    def test_reset_keeps_database_empty_for_subsequent_requests(self):
        self.assertEqual(self.client.post("/admin/reset-db", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/health").json["counts"],
                         {"produtos": 0, "usuarios": 0, "pedidos": 0})
        self.assertEqual(self.client.get("/produtos").json["dados"], [])

    def test_health_error_has_safe_original_shape(self):
        with patch.object(self.database, "connect", side_effect=RuntimeError("detalhe privado")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"status": "erro", "detalhes": "Erro interno"})

    def test_teardown_rolls_back_pending_writes(self):
        before = self.snapshot()
        original = ProductRepository.all

        def write_without_commit(repository):
            repository.connection().execute("UPDATE produtos SET estoque = estoque + 99 WHERE id = 1")
            return original(repository)

        with patch.object(ProductRepository, "all", write_without_commit):
            response = self.client.get("/produtos")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_connections_are_distinct_and_closed_after_requests(self):
        connections = []
        original = self.database.connect
        def collect():
            connection = original()
            connections.append(connection)
            return connection
        with patch.object(self.database, "connect", collect):
            self.client.get("/produtos")
            self.client.get("/produtos")
        self.assertEqual(len(connections), 2)
        self.assertIsNot(connections[0], connections[1])
        for connection in connections:
            try:
                connection.execute("SELECT 1")
            except Exception as error:
                self.assertEqual(type(error).__name__, "ProgrammingError")
            else:
                self.fail("A conexão permaneceu aberta")


if __name__ == "__main__":
    unittest.main()
