from flask import jsonify

from constants import API_VERSION


class SystemController:
    def __init__(self, service):
        self.service = service

    def index(self):
        return jsonify({
            "mensagem": "Bem-vindo à API da Loja", "versao": API_VERSION,
            "endpoints": {"produtos": "/produtos", "usuarios": "/usuarios",
                          "pedidos": "/pedidos", "login": "/login",
                          "relatorios": "/relatorios/vendas", "health": "/health"},
        })

    def health(self):
        return jsonify(self.service.health()), 200

    def reset(self):
        self.service.reset()
        return jsonify({"mensagem": "Banco de dados resetado", "sucesso": True}), 200

    def blocked_query(self):
        return jsonify({"erro": "Operação não permitida"}), 403
