"""Composição da aplicação, sem escrita no banco durante a importação."""
from flask import Flask
from flask_cors import CORS
from config.settings import settings_from_environment
from database import db, initialize_database
from middlewares.error_handler import register_error_handlers
from middlewares.json_request import ContractRequest
from routes import register_routes


def create_app(settings=None):
    app = Flask(__name__)
    app.request_class = ContractRequest
    app.config.from_mapping(settings_from_environment())
    if settings is not None:
        app.config.update(settings)
    db.init_app(app)
    CORS(app, origins=app.config['CORS_ORIGINS'])
    register_routes(app)
    register_error_handlers(app)
    return app


if __name__ == '__main__':
    application = create_app()
    initialize_database(application)
    application.run(host=application.config['HOST'], port=5000,
                    debug=application.config['DEBUG'])
