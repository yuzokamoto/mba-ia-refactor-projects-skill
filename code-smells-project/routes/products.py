from flask import Blueprint

from middlewares.auth import require_admin


def register_reads(bp, controller):
    bp.add_url_rule("/produtos", view_func=controller.all, methods=["GET"])
    bp.add_url_rule("/produtos/busca", view_func=controller.search, methods=["GET"])
    bp.add_url_rule("/produtos/<int:id>", view_func=controller.get, methods=["GET"])


def register_writes(bp, controller):
    bp.add_url_rule("/produtos", view_func=require_admin(controller.create), methods=["POST"])
    bp.add_url_rule("/produtos/<int:id>", view_func=require_admin(controller.update), methods=["PUT"])
    bp.add_url_rule("/produtos/<int:id>", view_func=require_admin(controller.delete), methods=["DELETE"])


def blueprint(controller):
    bp = Blueprint("products", __name__)
    register_reads(bp, controller)
    register_writes(bp, controller)
    return bp
