const { Router } = require('express');

function financialReportRoutes(controller, authenticate) {
    const router = Router();
    router.get('/api/admin/financial-report', authenticate, controller);
    return router;
}

module.exports = { financialReportRoutes };
