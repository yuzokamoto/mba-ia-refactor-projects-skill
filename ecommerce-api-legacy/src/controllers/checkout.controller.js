const { validateCheckout } = require('../validators/checkout.validator');

function createCheckoutController(service) {
    return async function checkout(req, res, next) {
        try {
            const data = validateCheckout(req.body);
            const result = await service.checkout(data);
            res.status(200).json({ msg: 'Sucesso', enrollment_id: result.enrollmentId });
        } catch (error) {
            next(error);
        }
    };
}

module.exports = { createCheckoutController };
