"""Exceções de domínio; o transporte HTTP é definido no middleware."""


class DomainError(Exception):
    pass


class ValidationError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class CredentialsError(DomainError):
    pass


class InactiveUserError(DomainError):
    pass


class PersistenceError(DomainError):
    pass
