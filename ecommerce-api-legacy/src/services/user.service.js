const { PersistenceError } = require('../errors/AppError');

function createUserService({ unitOfWork, users, enrollments, payments }) {
    async function remove(userId) {
        try {
            await unitOfWork.transaction(async () => {
                await payments.removeByUser(userId);
                await enrollments.removeByUser(userId);
                await users.remove(userId);
            });
        } catch (error) {
            throw new PersistenceError('Erro DB');
        }
    }

    return { remove };
}

module.exports = { createUserService };
