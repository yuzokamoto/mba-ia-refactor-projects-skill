class AppError extends Error {
    constructor(message) {
        super(message);
        this.name = this.constructor.name;
    }
}

class ValidationError extends AppError {}
class InvalidUserIdError extends ValidationError {}
class AuthenticationError extends AppError {}
class NotFoundError extends AppError {}
class PersistenceError extends AppError {}

module.exports = {
    AppError, ValidationError, InvalidUserIdError, AuthenticationError, NotFoundError, PersistenceError
};
