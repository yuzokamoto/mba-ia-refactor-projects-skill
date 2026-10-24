"""Mantém mensagens de domínio e páginas padrão do Flask."""
from flask import jsonify
from werkzeug.exceptions import HTTPException, InternalServerError
from errors import (ConflictError, CredentialsError, DomainError, InactiveUserError,
                    NotFoundError, PersistenceError, ValidationError)

DOMAIN_HTTP_CODES = {ValidationError: 400, NotFoundError: 404, ConflictError: 409,
                     CredentialsError: 401, InactiveUserError: 403, PersistenceError: 500}


def register_error_handlers(app):
    @app.errorhandler(DomainError)
    def domain_error(exc):
        if isinstance(exc, PersistenceError):
            # Não registra parâmetros SQL, credenciais ou texto bruto da exceção.
            app.logger.error('Falha de persistência (%s)', type(exc.__cause__).__name__)
        return jsonify({'error': str(exc)}), DOMAIN_HTTP_CODES[type(exc)]

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return exc
        app.logger.error('Falha inesperada (%s)', type(exc).__name__)
        return InternalServerError()
