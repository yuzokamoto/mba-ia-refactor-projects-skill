const sqlite3 = require('sqlite3');
const { PAYMENT_STATUS } = require('../constants/payment');
const { hashPassword } = require('../utils/password');
const { PersistenceError } = require('../errors/AppError');

async function createDatabase({ seedPassword } = {}) {
    const connection = await new Promise((resolve, reject) => {
        const opened = new sqlite3.Database(':memory:', error => {
            if (error) reject(error);
            else resolve(opened);
        });
    });
    let queue = Promise.resolve();

    // A fila inclui leituras para que nenhuma requisição veja uma transação parcial.
    function exclusive(operation) {
        const result = queue.then(operation);
        queue = result.catch(() => undefined);
        return result;
    }

    async function controlTransaction(sql) {
        try {
            await database.run(sql);
        } catch (error) {
            throw new PersistenceError('Erro DB');
        }
    }

    const database = {
        run(sql, parameters = []) {
            return new Promise((resolve, reject) => {
                connection.run(sql, parameters, function (error) {
                    if (error) reject(error);
                    else resolve({ id: this.lastID, changes: this.changes });
                });
            });
        },
        get(sql, parameters = []) {
            return new Promise((resolve, reject) => {
                connection.get(sql, parameters, (error, row) => {
                    if (error) reject(error);
                    else resolve(row);
                });
            });
        },
        all(sql, parameters = []) {
            return new Promise((resolve, reject) => {
                connection.all(sql, parameters, (error, rows) => {
                    if (error) reject(error);
                    else resolve(rows);
                });
            });
        },
        read: exclusive,
        transaction(operation) {
            return exclusive(async () => {
                await controlTransaction('BEGIN');
                try {
                    const result = await operation();
                    await controlTransaction('COMMIT');
                    return result;
                } catch (error) {
                    await controlTransaction('ROLLBACK');
                    throw error;
                }
            });
        },
        close() {
            return exclusive(() => new Promise((resolve, reject) => {
                connection.close(error => {
                    if (error) reject(error);
                    else resolve();
                });
            }));
        }
    };

    try {
        await database.run('PRAGMA foreign_keys = ON');
        await database.transaction(async () => {
            await database.run('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, pass TEXT)');
            await database.run('CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT, price REAL, active INTEGER)');
            await database.run(`CREATE TABLE enrollments (
                id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                course_id INTEGER REFERENCES courses(id))`);
            await database.run(`CREATE TABLE payments (
                id INTEGER PRIMARY KEY, enrollment_id INTEGER REFERENCES enrollments(id),
                amount REAL, status TEXT)`);
            await database.run('CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, action TEXT, created_at DATETIME)');
            await database.run('CREATE INDEX enrollment_user ON enrollments(user_id)');
            await database.run('CREATE INDEX enrollment_course ON enrollments(course_id)');
            await database.run('CREATE INDEX payment_enrollment ON payments(enrollment_id)');
            // Sem senha configurada, o seed continua público, mas sua autenticação fica desabilitada.
            const storedPassword = seedPassword ? hashPassword(seedPassword) : null;
            await database.run('INSERT INTO users (name, email, pass) VALUES (?, ?, ?)',
                ['Leonan', 'leonan@fullcycle.com.br', storedPassword]);
            await database.run('INSERT INTO courses (title, price, active) VALUES (?, ?, ?), (?, ?, ?)',
                ['Clean Architecture', 997.00, 1, 'Docker', 497.00, 1]);
            await database.run('INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)', [1, 1]);
            await database.run('INSERT INTO payments (enrollment_id, amount, status) VALUES (?, ?, ?)',
                [1, 997.00, PAYMENT_STATUS.PAID]);
        });
        return database;
    } catch (error) {
        await database.close();
        throw error;
    }
}

module.exports = { createDatabase };
