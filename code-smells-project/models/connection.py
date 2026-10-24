class ConnectionLifecycle:
    """Gerencia a conexão usando armazenamento de contexto injetado."""

    def __init__(self, database, context):
        self.database = database
        self.context = context

    def acquire(self):
        state = self.context()
        if "loja_connection" not in state:
            state["loja_connection"] = self.database.connect()
        return state["loja_connection"]

    def release(self, _error=None):
        connection = self.context().pop("loja_connection", None)
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()
