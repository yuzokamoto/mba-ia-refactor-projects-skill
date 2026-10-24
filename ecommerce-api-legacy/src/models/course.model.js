const { PAYMENT_STATUS } = require('../constants/payment');

function createCourseModel(database) {
    return {
        findActiveById(id) {
            return database.get('SELECT id, title, price FROM courses WHERE id = ? AND active = 1', [id]);
        },
        listFinancialTotals() {
            // C8: cursos sem matrículas primeiro; em cada grupo, id crescente e ordem determinística.
            return database.all(`SELECT c.id, c.title,
                COALESCE(SUM(CASE WHEN p.status = ? THEN p.amount ELSE 0 END), 0) AS revenue
                FROM courses c
                LEFT JOIN enrollments e ON e.course_id = c.id
                LEFT JOIN payments p ON p.enrollment_id = e.id
                GROUP BY c.id
                ORDER BY (COUNT(e.id) > 0), c.id ASC`, [PAYMENT_STATUS.PAID]);
        }
    };
}

module.exports = { createCourseModel };
