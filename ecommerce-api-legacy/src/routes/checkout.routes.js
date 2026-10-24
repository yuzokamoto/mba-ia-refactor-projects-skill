const { Router } = require('express');

function checkoutRoutes(controller) {
    const router = Router();
    router.post('/api/checkout', controller);
    return router;
}

module.exports = { checkoutRoutes };
