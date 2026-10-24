const { validateUserId } = require('../validators/user.validator');

function createUserController(service) {
    return async function removeUser(req, res, next) {
        try {
            const userId = validateUserId(req.params.id);
            await service.remove(userId);
            res.send('Usuário deletado');
        } catch (error) {
            next(error);
        }
    };
}

module.exports = { createUserController };
