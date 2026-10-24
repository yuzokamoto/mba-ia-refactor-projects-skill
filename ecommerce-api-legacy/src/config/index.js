function loadConfig(environment = process.env) {
    return {
        host: environment.HOST || '127.0.0.1',
        port: Number(environment.PORT || 3000),
        adminToken: environment.ADMIN_TOKEN,
        seedPassword: environment.SEED_USER_PASSWORD || undefined
    };
}

module.exports = { loadConfig };
