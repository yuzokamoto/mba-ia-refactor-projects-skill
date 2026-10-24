from flask import Blueprint

from middlewares.auth import require_admin


def blueprint(controller):
    bp = Blueprint("users", __name__)
    bp.add_url_rule("/usuarios", view_func=require_admin(controller.all), methods=["GET"])
    bp.add_url_rule("/usuarios/<int:id>", view_func=require_admin(controller.get), methods=["GET"])
    bp.add_url_rule("/usuarios", view_func=controller.create, methods=["POST"])
    bp.add_url_rule("/login", view_func=controller.login, methods=["POST"])
    return bp
