import hmac
from functools import wraps

from flask import current_app, jsonify, request


def require_admin(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        expected = current_app.config.get("ADMIN_TOKEN")
        given = request.headers.get("X-Admin-Token", "")
        if not expected or not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
            return jsonify({"erro": "Não autorizado"}), 401
        return view(*args, **kwargs)
    return guarded
