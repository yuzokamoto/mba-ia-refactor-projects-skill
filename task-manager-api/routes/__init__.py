"""Registro explícito dos Blueprints."""
from routes.category_routes import category_bp
from routes.report_routes import report_bp
from routes.system_routes import system_bp
from routes.task_routes import task_bp
from routes.user_routes import user_bp


def register_routes(app):
    for blueprint in (task_bp, user_bp, report_bp, category_bp, system_bp):
        app.register_blueprint(blueprint)
