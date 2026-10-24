"""Configuração lida a cada criação da aplicação."""
import os
import secrets


def settings_from_environment():
    return {
        'SQLALCHEMY_DATABASE_URI': os.environ.get('DATABASE_URL') or 'sqlite:///tasks.db',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SECRET_KEY': os.environ.get('SECRET_KEY') or secrets.token_hex(32),
        'ADMIN_TOKEN': os.environ.get('ADMIN_TOKEN'),
        'HOST': os.environ.get('HOST') or '127.0.0.1',
        'DEBUG': os.environ.get('FLASK_DEBUG', '0') == '1',
        'CORS_ORIGINS': [origin.strip() for origin in
                         os.environ.get('CORS_ORIGINS', '').split(',') if origin.strip()],
    }
