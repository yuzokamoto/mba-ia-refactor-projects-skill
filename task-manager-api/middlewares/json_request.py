"""Preserva a resposta legada de JSON malformado sem habilitar o depurador."""
from flask import Request
from werkzeug.wrappers import Request as WerkzeugRequest


class ContractRequest(Request):
    def on_json_loading_failed(self, error):
        return WerkzeugRequest.on_json_loading_failed(self, error)
