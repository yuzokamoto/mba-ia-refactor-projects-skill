class SystemRepository:
    def __init__(self, connection):
        self.connection = connection

    def counts(self):
        connection = self.connection()
        connection.execute("SELECT 1")
        return {
            "produtos": connection.execute("SELECT COUNT(*) FROM produtos").fetchone()[0],
            "usuarios": connection.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0],
            "pedidos": connection.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0],
        }

    def reset(self):
        connection = self.connection()
        with connection:
            connection.execute("DELETE FROM itens_pedido")
            connection.execute("DELETE FROM pedidos")
            connection.execute("DELETE FROM produtos")
            connection.execute("DELETE FROM usuarios")
