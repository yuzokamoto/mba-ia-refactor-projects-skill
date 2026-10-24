"""Usuários, consultas e verificação de hashes legados."""
import hashlib
import hmac
import string
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash
from database import db
from models.task import Task
from utils.clock import utc_now


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='user')
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'email': self.email,
                'role': self.role, 'active': self.active, 'created_at': str(self.created_at)}

    def set_password(self, raw):
        self.password = generate_password_hash(raw)

    def has_legacy_password(self):
        return (isinstance(self.password, str) and len(self.password) == 32
                and all(char in string.hexdigits for char in self.password))

    def check_password(self, raw):
        if self.has_legacy_password():
            # Compatibilidade somente para autenticar e migrar registros existentes.
            legacy = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
            return hmac.compare_digest(self.password, legacy)
        return check_password_hash(self.password, raw)


def get(user_id):
    return db.session.get(User, user_id)


def find_by_email(email):
    return db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def list_with_task_counts():
    statement = (select(User, func.count(Task.id)).outerjoin(Task, Task.user_id == User.id)
                 .group_by(User.id).order_by(User.id))
    return db.session.execute(statement).all()


def all_users():
    return db.session.execute(select(User).order_by(User.id)).scalars().all()


def clear():
    db.session.execute(db.delete(User))
