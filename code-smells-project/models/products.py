PRODUCT_FIELDS = ("id", "nome", "descricao", "preco", "estoque", "categoria", "ativo", "criado_em")


def serialize_product(row):
    return {field: row[field] for field in PRODUCT_FIELDS}


class ProductRepository:
    def __init__(self, connection):
        self.connection = connection

    def all(self):
        rows = self.connection().execute("SELECT * FROM produtos ORDER BY id").fetchall()
        return [serialize_product(row) for row in rows]

    def find(self, product_id):
        row = self.connection().execute("SELECT * FROM produtos WHERE id = ?", (product_id,)).fetchone()
        return serialize_product(row) if row is not None else None

    def find_many(self, product_ids, connection):
        placeholders = ",".join("?" for _ in product_ids)
        rows = connection.execute("SELECT * FROM produtos WHERE id IN (" + placeholders + ")",
                                  tuple(product_ids)).fetchall()
        return {row["id"]: serialize_product(row) for row in rows}

    def create(self, data):
        connection = self.connection()
        with connection:
            result = connection.execute(
                "INSERT INTO produtos (nome, descricao, preco, estoque, categoria) VALUES (?, ?, ?, ?, ?)",
                tuple(data[field] for field in ("nome", "descricao", "preco", "estoque", "categoria")),
            )
        return result.lastrowid

    def update(self, product_id, data):
        connection = self.connection()
        with connection:
            connection.execute(
                "UPDATE produtos SET nome = ?, descricao = ?, preco = ?, estoque = ?, categoria = ? WHERE id = ?",
                tuple(data[field] for field in ("nome", "descricao", "preco", "estoque", "categoria")) + (product_id,),
            )

    def delete(self, product_id):
        connection = self.connection()
        with connection:
            connection.execute("DELETE FROM produtos WHERE id = ?", (product_id,))

    def decrement_stock(self, product_id, quantity, connection):
        connection.execute("UPDATE produtos SET estoque = estoque - ? WHERE id = ?", (quantity, product_id))

    def search(self, term, category, minimum, maximum):
        clauses, parameters = [], []
        if term:
            clauses.append("(nome LIKE ? OR descricao LIKE ?)")
            parameters.extend(("%" + term + "%", "%" + term + "%"))
        if category:
            clauses.append("categoria = ?")
            parameters.append(category)
        # O limite zero mantém o comportamento original, que ignora valores falsos.
        if minimum:
            clauses.append("preco >= ?")
            parameters.append(minimum)
        if maximum:
            clauses.append("preco <= ?")
            parameters.append(maximum)
        statement = "SELECT * FROM produtos"
        if clauses:
            statement += " WHERE " + " AND ".join(clauses)
        rows = self.connection().execute(statement + " ORDER BY id", parameters).fetchall()
        return [serialize_product(row) for row in rows]
