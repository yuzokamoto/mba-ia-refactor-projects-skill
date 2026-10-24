from flask import Blueprint

from middlewares.auth import require_admin


def blueprint(controller):
    bp = Blueprint("orders", __name__)
    bp.add_url_rule("/pedidos", view_func=require_admin(controller.create), methods=["POST"])
    bp.add_url_rule("/pedidos", view_func=require_admin(controller.all), methods=["GET"])
    bp.add_url_rule("/pedidos/usuario/<int:usuario_id>", view_func=require_admin(controller.by_user), methods=["GET"])
    bp.add_url_rule("/pedidos/<int:pedido_id>/status", view_func=require_admin(controller.update_status), methods=["PUT"])
    return bp
