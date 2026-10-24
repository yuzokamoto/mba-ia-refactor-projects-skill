USER_FIELDS = ("id", "nome", "email", "tipo", "criado_em")
LOGIN_FIELDS = ("id", "nome", "email", "tipo")


def serialize_user(row, fields=USER_FIELDS):
    return {field: row[field] for field in fields}


class UserRepository:
    def __init__(self, connection):
        self.connection = connection

    def all(self):
        return [serialize_user(row) for row in
                self.connection().execute("SELECT * FROM usuarios ORDER BY id").fetchall()]

    def find(self, user_id):
        row = self.connection().execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        return serialize_user(row) if row is not None else None

    def by_email(self, email):
        return self.connection().execute("SELECT * FROM usuarios WHERE email = ? ORDER BY id", (email,)).fetchall()

    def create(self, name, email, password_hash):
        connection = self.connection()
        with connection:
            result = connection.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                (name, email, password_hash, "cliente"),
            )
        return result.lastrowid

    def replace_password(self, user_id, previous, password_hash):
        connection = self.connection()
        with connection:
            connection.execute("UPDATE usuarios SET senha = ? WHERE id = ? AND senha = ?",
                               (password_hash, user_id, previous))
