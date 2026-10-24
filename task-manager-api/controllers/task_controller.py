from flask import jsonify, request
from services import task_service
from validators import task_validator


def get_tasks():
    return jsonify(task_service.list_tasks()), 200


def get_task(task_id):
    return jsonify(task_service.get_task(task_id)), 200


def create_task():
    payload = task_validator.payload(request.get_json(), create=True)
    return jsonify(task_service.create_task(payload)), 201


def update_task(task_id):
    task = task_service.require_task(task_id)
    payload = task_validator.payload(request.get_json())
    return jsonify(task_service.update_task(task, payload)), 200


def delete_task(task_id):
    task_service.delete_task(task_id)
    return jsonify({'message': 'Task deletada com sucesso'}), 200


def search_tasks():
    filters = task_validator.search_query(request.args)
    return jsonify(task_service.search_tasks(filters)), 200


def task_stats():
    return jsonify(task_service.stats()), 200
