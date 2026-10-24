from contextlib import contextmanager


class OrderRepository:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def transaction(self):
        connection = self.connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def insert(self, user_id, total, connection):
        result = connection.execute("INSERT INTO pedidos (usuario_id, status, total) VALUES (?, ?, ?)",
                                    (user_id, "pendente", total))
        return result.lastrowid

    def insert_item(self, order_id, product_id, quantity, price, connection):
        connection.execute(
            "INSERT INTO itens_pedido (pedido_id, produto_id, quantidade, preco_unitario) VALUES (?, ?, ?, ?)",
            (order_id, product_id, quantity, price),
        )

    def list(self, user_id=None):
        connection = self.connection()
        statement, parameters = "SELECT * FROM pedidos", ()
        if user_id is not None:
            statement += " WHERE usuario_id = ?"
            parameters = (user_id,)
        orders = [dict(row, itens=[]) for row in connection.execute(statement + " ORDER BY id", parameters)]
        if not orders:
            return orders
        by_id = {order["id"]: order for order in orders}
        placeholders = ",".join("?" for _ in by_id)
        items = connection.execute(
            "SELECT i.pedido_id, i.produto_id, i.quantidade, i.preco_unitario, "
            "CASE WHEN p.id IS NULL THEN 'Desconhecido' ELSE p.nome END AS produto_nome "
            "FROM itens_pedido i LEFT JOIN produtos p ON p.id = i.produto_id "
            "WHERE i.pedido_id IN (" + placeholders + ") ORDER BY i.id", tuple(by_id),
        )
        for row in items:
            by_id[row["pedido_id"]]["itens"].append({field: row[field] for field in
                ("produto_id", "produto_nome", "quantidade", "preco_unitario")})
        return orders

    def update_status(self, order_id, new_status):
        connection = self.connection()
        with connection:
            connection.execute("UPDATE pedidos SET status = ? WHERE id = ?", (new_status, order_id))
