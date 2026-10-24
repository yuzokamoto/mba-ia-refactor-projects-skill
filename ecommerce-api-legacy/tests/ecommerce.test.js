const { test } = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const express = require('express');
const { createApp } = require('../src/app');
const { createDatabase } = require('../src/models/db');
const { loadConfig } = require('../src/config');
const { startServer } = require('../src/server');
const { createCheckoutController } = require('../src/controllers/checkout.controller');
const { createFinancialReportController } = require('../src/controllers/financialReport.controller');
const { createUserController } = require('../src/controllers/user.controller');
const { createErrorHandler } = require('../src/middlewares/errorHandler');
const { checkoutRoutes } = require('../src/routes/checkout.routes');
const { financialReportRoutes } = require('../src/routes/financialReport.routes');
const { userRoutes } = require('../src/routes/user.routes');
const { hashPassword, verifyPassword } = require('../src/utils/password');

function credential() {
    return randomBytes(24).toString('base64url');
}

async function listen(app) {
    return new Promise(resolve => {
        const server = app.listen(0, '127.0.0.1', () => resolve(server));
    });
}

async function fixture(context, { adminEnabled = true, seedEnabled = true } = {}) {
    const admin = credential();
    const password = credential();
    const logs = [];
    const database = await createDatabase({ seedPassword: seedEnabled ? password : undefined });
    const app = createApp({ database, config: { adminToken: adminEnabled ? admin : undefined },
        logger: { error: message => logs.push(message) } });
    const server = await listen(app);
    context.after(async () => {
        await new Promise(resolve => server.close(resolve));
        await database.close();
    });
    async function request(path, { method = 'GET', body, authorized = false, token, rawBody } = {}) {
        const headers = {};
        if (authorized) headers['X-Admin-Token'] = admin;
        if (token !== undefined) headers['X-Admin-Token'] = token;
        let payload;
        if (body !== undefined || rawBody !== undefined) {
            headers['Content-Type'] = 'application/json';
            payload = rawBody === undefined ? JSON.stringify(body) : rawBody;
        }
        const response = await fetch(`http://127.0.0.1:${server.address().port}${path}`, {
            method, headers, body: payload
        });
        const text = await response.text();
        return { status: response.status, type: response.headers.get('content-type'), text,
            json: response.headers.get('content-type').includes('application/json') ? JSON.parse(text) : undefined };
    }
    function checkout(overrides = {}) {
        return { usr: 'Leonan', eml: 'leonan@fullcycle.com.br', pwd: password, c_id: 2, card: '4', ...overrides };
    }
    async function counts() {
        const tables = ['users', 'enrollments', 'payments', 'audit_logs'];
        return Promise.all(tables.map(table => database.get(`SELECT COUNT(*) AS count FROM ${table}`)))
            .then(rows => rows.map(row => row.count));
    }
    return { database, request, checkout, counts, password, admin, logs };
}

test('C1: relatório e exclusão exigem token válido, sem expor a credencial', async context => {
    const f = await fixture(context);
    for (const [path, method] of [['/api/admin/financial-report', 'GET'], ['/api/users/1', 'DELETE']]) {
        for (const options of [{}, { token: credential() }]) {
            const response = await f.request(path, { method, ...options });
            assert.equal(response.status, 401);
            assert.deepEqual(response.json, { error: 'Não autorizado' });
        }
    }
    assert.equal((await f.request('/api/admin/financial-report', { authorized: true })).status, 200);
    assert.equal((await f.request('/api/users/999', { method: 'DELETE', authorized: true })).text, 'Usuário deletado');
    assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
});

test('C1/C2: ausência de configuração desabilita administração e autenticação do seed', async context => {
    const f = await fixture(context, { adminEnabled: false, seedEnabled: false });
    assert.equal((await f.request('/api/admin/financial-report', { authorized: true })).status, 401);
    assert.equal((await f.request('/api/users/1', { method: 'DELETE', authorized: true })).status, 401);
    const response = await f.request('/api/checkout', { method: 'POST', body: f.checkout() });
    assert.equal(response.status, 401);
    assert.deepEqual(response.json, { error: 'Credenciais inválidas' });
});

test('C2: conta existente exige senha; conta nova exige senha sem valor padrão', async context => {
    const f = await fixture(context);
    for (const password of [undefined, '', credential()]) {
        const response = await f.request('/api/checkout', { method: 'POST', body: f.checkout({ pwd: password }) });
        assert.equal(response.status, 401);
        assert.deepEqual(response.json, { error: 'Credenciais inválidas' });
    }
    for (const password of [undefined, '']) {
        const response = await f.request('/api/checkout', { method: 'POST',
            body: f.checkout({ eml: 'novo@example.test', pwd: password }) });
        assert.equal(response.status, 400);
        assert.equal(response.text, 'Senha obrigatória');
    }
    const password = credential();
    const response = await f.request('/api/checkout', { method: 'POST',
        body: f.checkout({ usr: 'Nova pessoa', eml: 'novo@example.test', pwd: password }) });
    assert.equal(response.status, 200);
    assert.deepEqual(response.json, { msg: 'Sucesso', enrollment_id: 2 });
    const stored = await f.database.get('SELECT pass FROM users WHERE email = ?', ['novo@example.test']);
    assert.ok(stored.pass !== password);
    assert.ok(verifyPassword(password, stored.pass));
    const again = await f.request('/api/checkout', { method: 'POST',
        body: f.checkout({ eml: 'novo@example.test', pwd: password }) });
    assert.equal(again.status, 200);
});

test('senhas usam salt aleatório e comparação segura, sem hashes nas respostas', () => {
    const password = credential();
    const first = hashPassword(password);
    const second = hashPassword(password);
    assert.ok(first !== second);
    assert.ok(verifyPassword(password, first));
    assert.ok(!verifyPassword(credential(), first));
    assert.ok(!verifyPassword(password, 'formato inválido'));
});

test('C3: tipos, corpo e IDs inválidos retornam os formatos aprovados', async context => {
    const f = await fixture(context);
    for (const body of [null, [], 'texto', true, 1,
        f.checkout({ card: 4 }), f.checkout({ card: [] }), f.checkout({ usr: {} }),
        f.checkout({ eml: false }), f.checkout({ pwd: null }), f.checkout({ c_id: true }),
        f.checkout({ c_id: -1 }), f.checkout({ c_id: '1.5' }), f.checkout({ c_id: 0 })]) {
        const response = await f.request('/api/checkout', { method: 'POST', body });
        assert.equal(response.status, 400);
        assert.equal(response.text, 'Bad Request');
    }
    for (const id of ['invalid', '0', '-1', '1.5']) {
        const response = await f.request('/api/users/' + id, { method: 'DELETE', authorized: true });
        assert.equal(response.status, 400);
        assert.deepEqual(response.json, { error: 'ID inválido' });
    }
    const valid = await f.request('/api/checkout', { method: 'POST', body: f.checkout({ c_id: '2' }) });
    assert.equal(valid.status, 200);
});

test('C4: recusa de pagamento não cria usuário nem altera o relatório', async context => {
    const f = await fixture(context);
    const before = await f.request('/api/admin/financial-report', { authorized: true });
    const response = await f.request('/api/checkout', { method: 'POST',
        body: f.checkout({ eml: 'recusado@example.test', card: '5' }) });
    assert.equal(response.status, 400);
    assert.equal(response.text, 'Pagamento recusado');
    assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
    const after = await f.request('/api/admin/financial-report', { authorized: true });
    assert.deepEqual(after.json, before.json);
});

for (const [table, message] of [
    ['users', 'Erro ao criar usuário'], ['enrollments', 'Erro Matrícula'],
    ['payments', 'Erro Pagamento'], ['audit_logs', 'Erro Auditoria']
]) {
    test(`C4/C5: falha em ${table} desfaz todo o checkout`, async context => {
        const f = await fixture(context);
        const run = f.database.run;
        f.database.run = (sql, parameters) => {
            if (sql.startsWith('INSERT INTO ' + table + ' ')) return Promise.reject(new Error('Falha simulada'));
            return run(sql, parameters);
        };
        const response = await f.request('/api/checkout', { method: 'POST',
            body: f.checkout({ eml: 'falha@example.test' }) });
        f.database.run = run;
        assert.equal(response.status, 500);
        assert.equal(response.text, message);
        assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
        const recovered = await f.request('/api/checkout', { method: 'POST', body: f.checkout() });
        assert.equal(recovered.status, 200);
        assert.equal(recovered.json.enrollment_id, 2);
    });
}

test('C5: erro de consulta de curso é 500 e curso ausente continua 404', async context => {
    const f = await fixture(context);
    const get = f.database.get;
    f.database.get = () => Promise.reject(new Error('Falha simulada'));
    const failed = await f.request('/api/checkout', { method: 'POST', body: f.checkout() });
    f.database.get = get;
    assert.equal(failed.status, 500);
    assert.equal(failed.text, 'Erro DB');
    const missing = await f.request('/api/checkout', { method: 'POST', body: f.checkout({ c_id: 999 }) });
    assert.equal(missing.status, 404);
    assert.equal(missing.text, 'Curso não encontrado');
});

test('C5: ambas as consultas do relatório propagam falhas com Erro DB', async context => {
    const f = await fixture(context);
    const all = f.database.all;
    for (const fragment of ['FROM courses', 'FROM enrollments']) {
        f.database.all = (sql, parameters) => sql.includes(fragment) ?
            Promise.reject(new Error('Falha simulada')) : all(sql, parameters);
        const response = await f.request('/api/admin/financial-report', { authorized: true });
        assert.equal(response.status, 500);
        assert.equal(response.text, 'Erro DB');
    }
    f.database.all = all;
});

test('C5: erro inesperado das três rotas retorna JSON genérico', async context => {
    const failure = async () => { throw new Error('Detalhe interno simulado'); };
    const app = express();
    app.use(express.json());
    const authenticate = (req, res, next) => next();
    app.use(checkoutRoutes(createCheckoutController({ checkout: failure })));
    app.use(financialReportRoutes(createFinancialReportController({ generate: failure }), authenticate));
    app.use(userRoutes(createUserController({ remove: failure }), authenticate));
    const logs = [];
    app.use(createErrorHandler({ error: message => logs.push(message) }));
    const server = await listen(app);
    context.after(() => new Promise(resolve => server.close(resolve)));
    for (const [path, method, body] of [
        ['/api/checkout', 'POST', { usr: 'Pessoa', eml: 'pessoa@example.test', c_id: 1, card: '4' }],
        ['/api/admin/financial-report', 'GET'], ['/api/users/1', 'DELETE']
    ]) {
        const response = await fetch(`http://127.0.0.1:${server.address().port}${path}`, {
            method, headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body)
        });
        assert.equal(response.status, 500);
        assert.deepEqual(await response.json(), { error: 'Erro interno' });
    }
    assert.equal(logs.length, 3);
    assert.ok(logs.every(message => !message.includes('Detalhe interno')));
});

test('C6: exclusão remove matrículas e pagamentos e é idempotente', async context => {
    const f = await fixture(context);
    const response = await f.request('/api/users/1', { method: 'DELETE', authorized: true });
    assert.equal(response.status, 200);
    assert.equal(response.text, 'Usuário deletado');
    assert.deepEqual(await f.counts(), [0, 0, 0, 0]);
    const report = await f.request('/api/admin/financial-report', { authorized: true });
    assert.ok(report.json.every(course => course.revenue === 0 && course.students.length === 0));
    assert.equal((await f.request('/api/users/1', { method: 'DELETE', authorized: true })).status, 200);
});

test('C5/C6: falha de exclusão restaura usuário, matrículas e pagamentos', async context => {
    const f = await fixture(context);
    const run = f.database.run;
    f.database.run = (sql, parameters) => sql.startsWith('DELETE FROM users ') ?
        Promise.reject(new Error('Falha simulada')) : run(sql, parameters);
    const response = await f.request('/api/users/1', { method: 'DELETE', authorized: true });
    f.database.run = run;
    assert.equal(response.status, 500);
    assert.equal(response.text, 'Erro DB');
    assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
});

test('C4: checkouts concorrentes isolam rollback, usuários e leituras', async context => {
    const f = await fixture(context);
    const run = f.database.run;
    let failed = false;
    f.database.run = (sql, parameters) => {
        if (!failed && sql.startsWith('INSERT INTO audit_logs ')) {
            failed = true;
            return Promise.reject(new Error('Falha simulada'));
        }
        return run(sql, parameters);
    };
    const password = credential();
    const responses = await Promise.all(Array.from({ length: 5 }, () => f.request('/api/checkout', {
        method: 'POST', body: f.checkout({ usr: 'Concorrente', eml: 'concorrente@example.test', pwd: password })
    })));
    f.database.run = run;
    assert.equal(responses.filter(response => response.status === 500).length, 1);
    assert.equal(responses.filter(response => response.status === 200).length, 4);
    assert.deepEqual(await f.counts(), [2, 5, 5, 4]);
    const report = await f.request('/api/admin/financial-report', { authorized: true });
    const docker = report.json.find(course => course.course === 'Docker');
    assert.equal(docker.revenue, 4 * 497);
    assert.equal(docker.students.length, 4);
});

test('C4: relatório aguarda o rollback de um checkout em andamento', async context => {
    const f = await fixture(context);
    const run = f.database.run;
    let enteredAudit;
    const auditStarted = new Promise(resolve => { enteredAudit = resolve; });
    let rejectAudit;
    f.database.run = (sql, parameters) => {
        if (sql.startsWith('INSERT INTO audit_logs ')) {
            enteredAudit();
            return new Promise((resolve, reject) => { rejectAudit = reject; });
        }
        return run(sql, parameters);
    };
    const checkout = f.request('/api/checkout', { method: 'POST', body: f.checkout() });
    await auditStarted;
    const all = f.database.all;
    let queriedDuringTransaction = false;
    f.database.all = (...args) => {
        queriedDuringTransaction = true;
        return all(...args);
    };
    const read = f.database.read;
    let enteredRead;
    const readStarted = new Promise(resolve => { enteredRead = resolve; });
    f.database.read = operation => {
        enteredRead();
        return read(operation);
    };
    let reportFinished = false;
    const report = f.request('/api/admin/financial-report', { authorized: true })
        .then(response => { reportFinished = true; return response; });
    await readStarted;
    await new Promise(resolve => setImmediate(resolve));
    const waitedForTransaction = !reportFinished && !queriedDuringTransaction;
    rejectAudit(new Error('Falha simulada'));
    assert.equal((await checkout).status, 500);
    const response = await report;
    f.database.run = run;
    f.database.all = all;
    f.database.read = read;
    assert.ok(waitedForTransaction);
    assert.deepEqual(response.json, [
        { course: 'Docker', revenue: 0, students: [] },
        { course: 'Clean Architecture', revenue: 997, students: [{ student: 'Leonan', paid: 997 }] }
    ]);
    assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
});

test('C5: falha inesperada de criptografia retorna JSON seguro e faz rollback', async context => {
    const f = await fixture(context);
    const passwords = require('../src/utils/password');
    const original = passwords.hashPassword;
    passwords.hashPassword = () => { throw new Error('Detalhe interno simulado'); };
    try {
        const response = await f.request('/api/checkout', { method: 'POST',
            body: f.checkout({ eml: 'inesperado@example.test' }) });
        assert.equal(response.status, 500);
        assert.deepEqual(response.json, { error: 'Erro interno' });
        assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
    } finally {
        passwords.hashPassword = original;
    }
});

test('relatório faz quantidade constante de consultas e mantém a receita e os alunos', async context => {
    const f = await fixture(context);
    await f.request('/api/checkout', { method: 'POST', body: f.checkout() });
    const all = f.database.all;
    const get = f.database.get;
    let queries = 0;
    f.database.all = (...args) => { queries++; return all(...args); };
    f.database.get = (...args) => { queries++; return get(...args); };
    const response = await f.request('/api/admin/financial-report', { authorized: true });
    f.database.all = all;
    f.database.get = get;
    assert.equal(queries, 2);
    assert.deepEqual(response.json, [
        { course: 'Clean Architecture', revenue: 997, students: [{ student: 'Leonan', paid: 997 }] },
        { course: 'Docker', revenue: 497, students: [{ student: 'Leonan', paid: 497 }] }
    ]);
});

test('C8: cursos sem matrículas primeiro e id crescente dentro de cada grupo', async context => {
    const f = await fixture(context);
    await f.database.transaction(async () => {
        await f.database.run('INSERT INTO courses (title, price, active) VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)',
            ['Curso 3', 10, 1, 'Curso 4', 10, 1, 'Curso 5', 10, 1]);
        await f.database.run('INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)', [1, 4]);
    });
    const expected = ['Docker', 'Curso 3', 'Curso 5', 'Clean Architecture', 'Curso 4'];
    for (let attempt = 0; attempt < 3; attempt++) {
        const response = await f.request('/api/admin/financial-report', { authorized: true });
        assert.equal(response.status, 200);
        assert.deepEqual(response.json.map(course => course.course), expected);
    }
});

test('páginas padrão do Express permanecem HTML; logs não recebem cartão ou senha', async context => {
    const f = await fixture(context);
    for (const [path, options, status] of [
        ['/inexistente', {}, 404],
        ['/api/checkout', { method: 'PATCH' }, 404],
        ['/api/checkout', { method: 'POST', rawBody: '{"' }, 400]
    ]) {
        const response = await f.request(path, options);
        assert.equal(response.status, status);
        assert.ok(response.type.includes('text/html'));
    }
    await f.request('/api/checkout', { method: 'POST', body: f.checkout() });
    assert.ok(f.logs.every(message => !message.includes(f.password) && !message.includes(f.admin)));
});

test('C3: parsing permissivo de JSON primitivo fica restrito ao checkout', async context => {
    const f = await fixture(context);
    for (const [path, method] of [
        ['/api/users/1', 'DELETE'], ['/api/admin/financial-report', 'PATCH'], ['/inexistente', 'POST']
    ]) {
        const response = await f.request(path, { method, authorized: true, body: null });
        assert.equal(response.status, 400);
        assert.ok(response.type.includes('text/html'));
    }
    assert.deepEqual(await f.counts(), [1, 1, 1, 0]);
    const response = await f.request('/API/CHECKOUT/', { method: 'POST', body: null });
    assert.equal(response.status, 400);
    assert.equal(response.text, 'Bad Request');
});

test('C7: configuração padrão e inicialização escutam apenas em loopback', async context => {
    const defaults = loadConfig({});
    assert.equal(defaults.host, '127.0.0.1');
    assert.equal(defaults.port, 3000);
    const custom = loadConfig({ HOST: '127.0.0.2', PORT: '3456' });
    assert.equal(custom.host, '127.0.0.2');
    assert.equal(custom.port, 3456);
    const running = await startServer({ ...defaults, port: 0 });
    context.after(() => running.stop());
    assert.equal(running.server.address().address, '127.0.0.1');
    const response = await fetch(`http://127.0.0.1:${running.server.address().port}/api/admin/financial-report`);
    assert.equal(response.status, 401);
    await running.stop();
    assert.ok(!running.server.listening);
});
