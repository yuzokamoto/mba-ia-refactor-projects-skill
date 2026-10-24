const { createApp } = require('./app');
const { loadConfig } = require('./config');
const { createDatabase } = require('./models/db');

async function startServer(config = loadConfig()) {
    const database = await createDatabase({ seedPassword: config.seedPassword });
    const app = createApp({ database, config });
    let server;
    try {
        server = await new Promise((resolve, reject) => {
            const listening = app.listen(config.port, config.host, () => resolve(listening));
            listening.once('error', reject);
        });
    } catch (error) {
        await database.close();
        throw error;
    }
    let stopping;
    function stop() {
        if (!stopping) {
            process.removeListener('SIGTERM', shutdown);
            process.removeListener('SIGINT', shutdown);
            stopping = new Promise((resolve, reject) => {
                server.close(error => error ? reject(error) : resolve());
            }).finally(() => database.close());
        }
        return stopping;
    }
    function shutdown() {
        stop().then(() => process.exit(0), () => process.exit(1));
    }
    process.once('SIGTERM', shutdown);
    process.once('SIGINT', shutdown);
    console.log(`Frankenstein LMS rodando na porta ${server.address().port}...`);
    return { server, stop };
}

module.exports = { startServer };
