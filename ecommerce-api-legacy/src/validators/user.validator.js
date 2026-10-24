const { InvalidUserIdError } = require('../errors/AppError');
const { positiveInteger } = require('./checkout.validator');

function validateUserId(id) {
    if (!positiveInteger(id)) throw new InvalidUserIdError('ID inválido');
    return id;
}

module.exports = { validateUserId };
