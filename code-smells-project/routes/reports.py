from flask import Blueprint

from middlewares.auth import require_admin


def blueprint(controller):
    bp = Blueprint("reports", __name__)
    bp.add_url_rule("/relatorios/vendas", view_func=require_admin(controller.sales), methods=["GET"])
    return bp
