from flask import current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import AuthenticationError, DomainError, NotFoundError, ValidationError


def register_error_handlers(app):
    @app.errorhandler(DomainError)
    def domain_error(error):
        if isinstance(error, NotFoundError):
            status = 404
        elif isinstance(error, AuthenticationError):
            status = 401
        elif isinstance(error, ValidationError):
            status = 400
        else:
            status = 500
        payload = {"erro": str(error)}
        if error.success is not None:
            payload["sucesso"] = error.success
        return jsonify(payload), status

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        # Não registrar o texto da exceção, que pode conter dados da requisição.
        current_app.logger.error("Erro interno durante o processamento da requisição")
        if request.endpoint == "system.health":
            return jsonify({"status": "erro", "detalhes": "Erro interno"}), 500
        return jsonify({"erro": "Erro interno"}), 500
