from constants import DISCOUNT_TIERS


class ReportService:
    def __init__(self, reports):
        self.reports = reports

    def sales(self):
        values = self.reports.sales()
        count = values["total_pedidos"]
        revenue = values["faturamento"] if values["faturamento"] is not None else 0
        discount = 0
        for threshold, rate in DISCOUNT_TIERS:
            if revenue > threshold:
                discount = revenue * rate
                break
        return {
            "total_pedidos": count,
            "faturamento_bruto": round(revenue, 2),
            "desconto_aplicavel": round(discount, 2),
            "faturamento_liquido": round(revenue - discount, 2),
            "pedidos_pendentes": values["pendentes"],
            "pedidos_aprovados": values["aprovados"],
            "pedidos_cancelados": values["cancelados"],
            "ticket_medio": round(revenue / count, 2) if count > 0 else 0,
        }
