const { randomBytes, scryptSync, timingSafeEqual } = require('node:crypto');

const SALT_BYTES = 16;
const HASH_BYTES = 64;

function hashPassword(password) {
    const salt = randomBytes(SALT_BYTES).toString('hex');
    const hash = scryptSync(password, salt, HASH_BYTES).toString('hex');
    return `${salt}:${hash}`;
}

function verifyPassword(password, stored) {
    if (typeof password !== 'string' || !password || typeof stored !== 'string') {
        return false;
    }
    const parts = stored.split(':');
    if (parts.length !== 2 || !/^[a-f0-9]{32}$/.test(parts[0]) ||
        !/^[a-f0-9]{128}$/.test(parts[1])) {
        return false;
    }
    const actual = scryptSync(password, parts[0], HASH_BYTES);
    return timingSafeEqual(actual, Buffer.from(parts[1], 'hex'));
}

module.exports = { hashPassword, verifyPassword };
