from flask import jsonify

from controllers.common import read_json
from validators.users import credentials


class UserController:
    def __init__(self, service):
        self.service = service

    def all(self):
        return jsonify({"dados": self.service.all(), "sucesso": True}), 200

    def get(self, **path):
        return jsonify({"dados": self.service.require(path["id"]), "sucesso": True}), 200

    def create(self):
        user_id = self.service.create(*credentials(read_json(), signup=True))
        return jsonify({"dados": {"id": user_id}, "sucesso": True}), 201

    def login(self):
        user = self.service.login(*credentials(read_json()))
        return jsonify({"dados": user, "sucesso": True, "mensagem": "Login OK"}), 200
