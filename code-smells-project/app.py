from flask import Flask
from flask_cors import CORS

from bootstrap import configure_application
from config.settings import Settings
from middlewares.error_handler import register_error_handlers


def create_app(settings=None, database=None):
    app = Flask(__name__)
    app.config.from_mapping(Settings.load())
    if settings is not None:
        app.config.update(settings)
    CORS(app, origins=app.config["CORS_ORIGINS"], always_send=False)
    register_error_handlers(app)
    configure_application(app, database)
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host=application.config["HOST"], port=5000,
                    debug=application.config["DEBUG"])
