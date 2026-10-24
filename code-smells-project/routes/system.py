from flask import Blueprint

from middlewares.auth import require_admin


def blueprint(controller):
    bp = Blueprint("system", __name__)
    bp.add_url_rule("/", view_func=controller.index, methods=["GET"])
    bp.add_url_rule("/health", view_func=controller.health, methods=["GET"])
    bp.add_url_rule("/admin/reset-db", view_func=require_admin(controller.reset), methods=["POST"])
    bp.add_url_rule("/admin/query", view_func=controller.blocked_query, methods=["POST"])
    return bp
