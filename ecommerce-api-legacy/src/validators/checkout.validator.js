const { ValidationError } = require('../errors/AppError');

function positiveInteger(value) {
    return (typeof value === 'number' && Number.isInteger(value) && value > 0) ||
        (typeof value === 'string' && /^\d+$/.test(value) && Number(value) > 0);
}

function validateCheckout(body) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
        throw new ValidationError('Bad Request');
    }
    if (![body.usr, body.eml, body.card].every(value => typeof value === 'string' && value.length > 0) ||
        !positiveInteger(body.c_id) || (body.pwd !== undefined && typeof body.pwd !== 'string')) {
        throw new ValidationError('Bad Request');
    }
    return {
        name: body.usr, email: body.eml, password: body.pwd,
        courseId: body.c_id, card: body.card
    };
}

module.exports = { validateCheckout, positiveInteger };
