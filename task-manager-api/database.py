from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def initialize_database(app):
    """Cria o esquema somente quando solicitado pelo comando de inicialização."""
    with app.app_context():
        db.create_all()
