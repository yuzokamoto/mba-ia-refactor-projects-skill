function createAuditLogModel(database) {
    return {
        recordCheckout(courseId, userId) {
            return database.run("INSERT INTO audit_logs (action, created_at) VALUES (?, datetime('now'))",
                [`Checkout curso ${courseId} por ${userId}`]);
        }
    };
}

module.exports = { createAuditLogModel };
