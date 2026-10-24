from flask import jsonify, request
from services import category_service
from validators import category_validator


def get_categories():
    return jsonify(category_service.list_categories()), 200


def create_category():
    payload = category_validator.payload(request.get_json(), create=True)
    return jsonify(category_service.create_category(payload)), 201


def update_category(cat_id):
    category = category_service.require_category(cat_id)
    payload = category_validator.payload(request.get_json())
    return jsonify(category_service.update_category(category, payload)), 200


def delete_category(cat_id):
    category_service.delete_category(cat_id)
    return jsonify({'message': 'Categoria deletada'}), 200
