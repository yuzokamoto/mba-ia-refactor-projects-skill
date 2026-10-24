"""Categorias e contagens de suas tarefas."""
from sqlalchemy import func, select
from constants import DEFAULT_COLOR
from database import db
from models.task import Task
from utils.clock import utc_now


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=True)
    color = db.Column(db.String(7), default=DEFAULT_COLOR)
    created_at = db.Column(db.DateTime, default=utc_now)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description,
                'color': self.color, 'created_at': str(self.created_at)}


def get(category_id):
    return db.session.get(Category, category_id)


def list_with_task_counts():
    statement = (select(Category, func.count(Task.id))
                 .outerjoin(Task, Task.category_id == Category.id)
                 .group_by(Category.id).order_by(Category.id))
    return db.session.execute(statement).all()


def count():
    return db.session.scalar(select(func.count(Category.id)))


def clear():
    db.session.execute(db.delete(Category))
