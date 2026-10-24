function createUserModel(database) {
    return {
        findByEmail(email) {
            return database.get('SELECT id, pass FROM users WHERE email = ?', [email]);
        },
        async create({ name, email, passwordHash }) {
            const result = await database.run('INSERT INTO users (name, email, pass) VALUES (?, ?, ?)',
                [name, email, passwordHash]);
            return result.id;
        },
        remove(id) {
            return database.run('DELETE FROM users WHERE id = ?', [id]);
        }
    };
}

module.exports = { createUserModel };
