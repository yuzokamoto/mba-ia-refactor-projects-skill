class DomainError(Exception):
    def __init__(self, message, success=None):
        super().__init__(message)
        self.success = success


class ValidationError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class AuthenticationError(DomainError):
    pass
