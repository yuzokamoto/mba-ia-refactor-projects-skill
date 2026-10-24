const express = require('express');
const { loadConfig } = require('./config');
const passwords = require('./utils/password');
const { createUserModel } = require('./models/user.model');
const { createCourseModel } = require('./models/course.model');
const { createEnrollmentModel } = require('./models/enrollment.model');
const { createPaymentModel } = require('./models/payment.model');
const { createAuditLogModel } = require('./models/auditLog.model');
const { createCheckoutService } = require('./services/checkout.service');
const { createFinancialReportService } = require('./services/financialReport.service');
const { createUserService } = require('./services/user.service');
const { createCheckoutController } = require('./controllers/checkout.controller');
const { createFinancialReportController } = require('./controllers/financialReport.controller');
const { createUserController } = require('./controllers/user.controller');
const { checkoutRoutes } = require('./routes/checkout.routes');
const { financialReportRoutes } = require('./routes/financialReport.routes');
const { userRoutes } = require('./routes/user.routes');
const { requireAdmin } = require('./middlewares/auth');
const { createErrorHandler } = require('./middlewares/errorHandler');
const { createJsonParser } = require('./middlewares/jsonParser');

function createApp({ database, config = loadConfig(), logger = console }) {
    const app = express();
    app.use(createJsonParser());
    const dependencies = {
        unitOfWork: database,
        users: createUserModel(database),
        courses: createCourseModel(database),
        enrollments: createEnrollmentModel(database),
        payments: createPaymentModel(database),
        auditLogs: createAuditLogModel(database),
        passwords
    };
    const authenticate = requireAdmin(config);
    app.use(checkoutRoutes(createCheckoutController(createCheckoutService(dependencies))));
    app.use(financialReportRoutes(
        createFinancialReportController(createFinancialReportService(dependencies)), authenticate));
    app.use(userRoutes(createUserController(createUserService(dependencies)), authenticate));
    app.use(createErrorHandler(logger));
    return app;
}

module.exports = { createApp };

if (require.main === module) {
    require('./server').startServer().catch(() => {
        console.error('Não foi possível iniciar a aplicação');
        process.exitCode = 1;
    });
}
