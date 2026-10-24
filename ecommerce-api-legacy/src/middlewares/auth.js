const { timingSafeEqual } = require('node:crypto');

function requireAdmin(config) {
    return function authenticate(req, res, next) {
        const expected = Buffer.from(config.adminToken || '');
        const given = Buffer.from(req.get('X-Admin-Token') || '');
        if (!expected.length || given.length !== expected.length || !timingSafeEqual(given, expected)) {
            return res.status(401).json({ error: 'Não autorizado' });
        }
        next();
    };
}

module.exports = { requireAdmin };
