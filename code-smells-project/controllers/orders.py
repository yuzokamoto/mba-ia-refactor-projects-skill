from flask import jsonify

from controllers.common import read_json
from validators.orders import order_payload, status_payload


class OrderController:
    def __init__(self, service):
        self.service = service

    def create(self):
        order = self.service.create(*order_payload(read_json()))
        return jsonify({"dados": order, "sucesso": True, "mensagem": "Pedido criado com sucesso"}), 201

    def all(self):
        return jsonify({"dados": self.service.list(), "sucesso": True}), 200

    def by_user(self, usuario_id):
        return jsonify({"dados": self.service.list(usuario_id), "sucesso": True}), 200

    def update_status(self, pedido_id):
        self.service.update_status(pedido_id, status_payload(read_json()))
        return jsonify({"sucesso": True, "mensagem": "Status atualizado"}), 200
