class ReportRepository:
    def __init__(self, connection):
        self.connection = connection

    def sales(self):
        return dict(self.connection().execute(
            "SELECT COUNT(*) AS total_pedidos, SUM(total) AS faturamento, "
            "COUNT(CASE WHEN status = 'pendente' THEN 1 END) AS pendentes, "
            "COUNT(CASE WHEN status = 'aprovado' THEN 1 END) AS aprovados, "
            "COUNT(CASE WHEN status = 'cancelado' THEN 1 END) AS cancelados FROM pedidos"
        ).fetchone())
