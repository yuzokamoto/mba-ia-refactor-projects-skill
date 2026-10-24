from flask import jsonify, request
from services import user_service
from validators.common import object_body
from validators.user_validator import login_payload


def get_users():
    return jsonify(user_service.list_users()), 200


def get_user(user_id):
    return jsonify(user_service.get_user(user_id)), 200


def create_user():
    payload = object_body(request.get_json())
    return jsonify(user_service.create_user(payload)), 201


def update_user(user_id):
    user = user_service.require_user(user_id)
    payload = object_body(request.get_json())
    return jsonify(user_service.update_user(user, payload)), 200


def delete_user(user_id):
    user_service.delete_user(user_id)
    return jsonify({'message': 'Usuário deletado com sucesso'}), 200


def get_user_tasks(user_id):
    return jsonify(user_service.user_tasks(user_id)), 200


def login():
    payload = login_payload(request.get_json())
    return jsonify(user_service.login(payload)), 200
