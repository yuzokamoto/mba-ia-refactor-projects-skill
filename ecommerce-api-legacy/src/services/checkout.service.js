const { PAYMENT_STATUS, APPROVED_CARD_PREFIX } = require('../constants/payment');
const { ValidationError, AuthenticationError, NotFoundError, PersistenceError } = require('../errors/AppError');

function createCheckoutService({ unitOfWork, users, courses, enrollments, payments, auditLogs, passwords }) {
    async function persist(operation, message) {
        try {
            return await operation();
        } catch (error) {
            throw new PersistenceError(message);
        }
    }

    async function checkout(data) {
        return unitOfWork.transaction(async () => {
            const course = await persist(() => courses.findActiveById(data.courseId), 'Erro DB');
            if (!course) throw new NotFoundError('Curso não encontrado');
            const existingUser = await persist(() => users.findByEmail(data.email), 'Erro DB');
            if (existingUser && !passwords.verifyPassword(data.password, existingUser.pass)) {
                throw new AuthenticationError('Credenciais inválidas');
            }
            if (!existingUser && !data.password) throw new ValidationError('Senha obrigatória');
            const paymentStatus = data.card.startsWith(APPROVED_CARD_PREFIX) ?
                PAYMENT_STATUS.PAID : PAYMENT_STATUS.DENIED;
            if (paymentStatus === PAYMENT_STATUS.DENIED) throw new ValidationError('Pagamento recusado');

            const passwordHash = existingUser ? undefined : passwords.hashPassword(data.password);
            const userId = existingUser ? existingUser.id : await persist(() => users.create({
                name: data.name, email: data.email, passwordHash
            }), 'Erro ao criar usuário');
            const enrollmentId = await persist(() => enrollments.create(userId, data.courseId), 'Erro Matrícula');
            await persist(() => payments.create(enrollmentId, course.price, paymentStatus), 'Erro Pagamento');
            await persist(() => auditLogs.recordCheckout(data.courseId, userId), 'Erro Auditoria');
            return { enrollmentId };
        });
    }

    return { checkout };
}

module.exports = { createCheckoutService };
