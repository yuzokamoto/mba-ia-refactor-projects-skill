const {
    AppError, ValidationError, InvalidUserIdError, AuthenticationError, NotFoundError, PersistenceError
} = require('../errors/AppError');

function createErrorHandler(logger) {
    return function errorHandler(error, req, res, next) {
        if (res.headersSent) return next(error);
        // Erros do parser seguem para o handler padrão do Express, preservando suas páginas.
        if (!(error instanceof AppError) && error.status && error.expose) return next(error);
        if (error instanceof AuthenticationError) {
            return res.status(401).json({ error: error.message });
        }
        if (error instanceof InvalidUserIdError) return res.status(400).json({ error: error.message });
        if (error instanceof ValidationError) return res.status(400).send(error.message);
        if (error instanceof NotFoundError) return res.status(404).send(error.message);
        if (error instanceof PersistenceError) return res.status(500).send(error.message);
        logger.error('Falha inesperada na requisição');
        return res.status(500).json({ error: 'Erro interno' });
    };
}

module.exports = { createErrorHandler };
