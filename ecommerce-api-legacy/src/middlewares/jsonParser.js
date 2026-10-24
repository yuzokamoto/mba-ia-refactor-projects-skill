const express = require('express');

function createJsonParser() {
    const standardParser = express.json();
    const checkoutParser = express.json({ strict: false });
    return function parseJson(req, res, next) {
        // Apenas o checkout recebeu a mudança de validação de corpos primitivos em C3.
        const isCheckout = req.method === 'POST' && /^\/api\/checkout\/?$/i.test(req.path);
        const parser = isCheckout ? checkoutParser : standardParser;
        return parser(req, res, next);
    };
}

module.exports = { createJsonParser };
