function createPaymentModel(database) {
    return {
        create(enrollmentId, amount, status) {
            return database.run('INSERT INTO payments (enrollment_id, amount, status) VALUES (?, ?, ?)',
                [enrollmentId, amount, status]);
        },
        removeByUser(userId) {
            return database.run(`DELETE FROM payments WHERE enrollment_id IN
                (SELECT id FROM enrollments WHERE user_id = ?)`, [userId]);
        }
    };
}

module.exports = { createPaymentModel };
