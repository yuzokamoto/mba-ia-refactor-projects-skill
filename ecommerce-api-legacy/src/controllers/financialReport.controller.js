function createFinancialReportController(service) {
    return async function financialReport(req, res, next) {
        try {
            const report = await service.generate();
            res.json(report);
        } catch (error) {
            next(error);
        }
    };
}

module.exports = { createFinancialReportController };
