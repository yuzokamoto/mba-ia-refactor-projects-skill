"""Comando explícito para popular o banco com credenciais do ambiente."""
import os
from app import create_app
from database import initialize_database
from services.seed_service import SEED_PASSWORD_NAMES, populate, validate_passwords


def seed_data(application=None, passwords=None):
    if passwords is None:
        passwords = {name: os.environ.get(name) for name in SEED_PASSWORD_NAMES}
    # A ausência de credenciais interrompe a operação antes de acessar o banco.
    validate_passwords(passwords)
    application = application if application is not None else create_app()
    initialize_database(application)
    with application.app_context():
        users, categories, tasks = populate(passwords)
    print('Seed concluído com sucesso!')
    print(f'  {users} usuários')
    print(f'  {categories} categorias')
    print(f'  {tasks} tasks')


if __name__ == '__main__':
    seed_data()
