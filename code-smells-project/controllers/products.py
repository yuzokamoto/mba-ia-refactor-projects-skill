from flask import jsonify, request

from controllers.common import read_json
from validators.products import product_payload, search_parameters


class ProductController:
    def __init__(self, service):
        self.service = service

    def all(self):
        return jsonify({"dados": self.service.all(), "sucesso": True}), 200

    def get(self, **path):
        product = self.service.require(path["id"], success=False)
        return jsonify({"dados": product, "sucesso": True}), 200

    def create(self):
        data = product_payload(read_json())
        product_id = self.service.create(data)
        return jsonify({"dados": {"id": product_id}, "sucesso": True, "mensagem": "Produto criado"}), 201

    def update(self, **path):
        data = read_json()
        self.service.require(path["id"])
        self.service.update(path["id"], product_payload(data, update=True))
        return jsonify({"sucesso": True, "mensagem": "Produto atualizado"}), 200

    def delete(self, **path):
        self.service.delete(path["id"])
        return jsonify({"sucesso": True, "mensagem": "Produto deletado"}), 200

    def search(self):
        results = self.service.search(*search_parameters(request.args))
        return jsonify({"dados": results, "total": len(results), "sucesso": True}), 200
