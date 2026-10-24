const { PersistenceError } = require('../errors/AppError');

function createFinancialReportService({ unitOfWork, courses, enrollments }) {
    async function generate() {
        try {
            return await unitOfWork.read(async () => {
                const totals = await courses.listFinancialTotals();
                const rows = await enrollments.listStudents();
                const studentsByCourse = new Map();
                for (const row of rows) {
                    if (!studentsByCourse.has(row.course_id)) studentsByCourse.set(row.course_id, []);
                    studentsByCourse.get(row.course_id).push({
                        student: row.name === null ? 'Unknown' : row.name,
                        paid: row.payment_id === null ? 0 : row.amount
                    });
                }
                return totals.map(course => ({
                    course: course.title, revenue: course.revenue,
                    students: studentsByCourse.get(course.id) || []
                }));
            });
        } catch (error) {
            throw new PersistenceError('Erro DB');
        }
    }

    return { generate };
}

module.exports = { createFinancialReportService };
