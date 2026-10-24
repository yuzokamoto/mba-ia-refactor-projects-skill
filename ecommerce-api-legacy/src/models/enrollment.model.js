function createEnrollmentModel(database) {
    return {
        async create(userId, courseId) {
            const result = await database.run('INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)',
                [userId, courseId]);
            return result.id;
        },
        removeByUser(userId) {
            return database.run('DELETE FROM enrollments WHERE user_id = ?', [userId]);
        },
        listStudents() {
            return database.all(`SELECT e.course_id, u.name, p.id AS payment_id, p.amount
                FROM enrollments e
                LEFT JOIN users u ON u.id = e.user_id
                LEFT JOIN payments p ON p.enrollment_id = e.id
                ORDER BY e.id`);
        }
    };
}

module.exports = { createEnrollmentModel };
