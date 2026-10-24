import os
import secrets


class Settings:
    @staticmethod
    def load():
        return {
            "SECRET_KEY": os.environ.get("SECRET_KEY") or secrets.token_hex(32),
            "ADMIN_TOKEN": os.environ.get("ADMIN_TOKEN"),
            "DEBUG": os.environ.get("FLASK_DEBUG", "0") == "1",
            "HOST": os.environ.get("HOST") or "127.0.0.1",
            "DATABASE_PATH": os.environ.get("DATABASE_PATH") or "loja.db",
            "CORS_ORIGINS": [origin.strip() for origin in
                             os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()],
            "SEED_PASSWORDS": {
                "admin": os.environ.get("SEED_ADMIN_PASSWORD"),
                "joao": os.environ.get("SEED_JOAO_PASSWORD"),
                "maria": os.environ.get("SEED_MARIA_PASSWORD"),
            },
        }
