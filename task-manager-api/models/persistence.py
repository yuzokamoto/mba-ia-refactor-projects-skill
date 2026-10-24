"""Unidade de trabalho usada explicitamente pelos serviços."""
from contextlib import contextmanager
from database import db
from errors import DomainError, PersistenceError


@contextmanager
def transaction(message):
    try:
        yield
        db.session.commit()
    except DomainError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        raise PersistenceError(message) from exc


def add(entity):
    db.session.add(entity)


def delete(entity):
    db.session.delete(entity)


def flush():
    db.session.flush()
