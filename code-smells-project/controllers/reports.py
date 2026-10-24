from flask import jsonify


class ReportController:
    def __init__(self, service):
        self.service = service

    def sales(self):
        return jsonify({"dados": self.service.sales(), "sucesso": True}), 200
