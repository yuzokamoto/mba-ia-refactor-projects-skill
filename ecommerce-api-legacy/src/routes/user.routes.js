const { Router } = require('express');

function userRoutes(controller, authenticate) {
    const router = Router();
    router.delete('/api/users/:id', authenticate, controller);
    return router;
}

module.exports = { userRoutes };
