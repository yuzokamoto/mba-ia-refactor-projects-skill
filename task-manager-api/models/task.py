"""Tarefas, projeção pública e consultas de persistência."""
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import joinedload
from constants import CLOSED_STATUSES, DEFAULT_PRIORITY, HIGH_PRIORITY_LIMIT
from database import db
from utils.clock import utc_now


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='pending')
    priority = db.Column(db.Integer, default=DEFAULT_PRIORITY)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)
    due_date = db.Column(db.DateTime, nullable=True)
    tags = db.Column(db.String(500), nullable=True)
    user = db.relationship('User', backref='tasks')
    category = db.relationship('Category', backref='tasks')

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'description': self.description,
            'status': self.status, 'priority': self.priority,
            'user_id': self.user_id, 'category_id': self.category_id,
            'created_at': str(self.created_at), 'updated_at': str(self.updated_at),
            'due_date': str(self.due_date) if self.due_date else None,
            'tags': self.tags.split(',') if self.tags else [],
        }

    def is_overdue(self, now=None):
        return bool(self.due_date and self.due_date < (now or utc_now())
                    and self.status not in CLOSED_STATUSES)


def get(task_id):
    return db.session.get(Task, task_id)


def list_with_relations():
    statement = (select(Task).options(joinedload(Task.user), joinedload(Task.category))
                 .order_by(Task.id))
    return db.session.execute(statement).scalars().all()


def for_user(user_id):
    return db.session.execute(select(Task).where(Task.user_id == user_id)
                              .order_by(Task.id)).scalars().all()


def search(query='', status='', priority=None, user_id=None):
    statement = select(Task)
    if query:
        statement = statement.where(or_(Task.title.like(f'%{query}%'),
                                        Task.description.like(f'%{query}%')))
    if status:
        statement = statement.where(Task.status == status)
    if priority is not None:
        statement = statement.where(Task.priority == priority)
    if user_id is not None:
        statement = statement.where(Task.user_id == user_id)
    return db.session.execute(statement.order_by(Task.id)).scalars().all()


def overdue_condition(now):
    return (Task.due_date < now) & or_(Task.status.not_in(CLOSED_STATUSES),
                                      Task.status.is_(None))


def status_counts(user_id=None):
    statement = select(Task.status, func.count(Task.id)).group_by(Task.status)
    if user_id is not None:
        statement = statement.where(Task.user_id == user_id)
    return dict(db.session.execute(statement).all())


def priority_counts():
    return dict(db.session.execute(select(Task.priority, func.count(Task.id))
                                   .group_by(Task.priority)).all())


def count_overdue(now, user_id=None):
    statement = select(func.count(Task.id)).where(overdue_condition(now))
    if user_id is not None:
        statement = statement.where(Task.user_id == user_id)
    return db.session.scalar(statement)


def overdue_tasks(now):
    return db.session.execute(select(Task).where(overdue_condition(now))
                              .order_by(Task.id)).scalars().all()


def recent_counts(since):
    created = db.session.scalar(select(func.count(Task.id)).where(Task.created_at >= since))
    completed = db.session.scalar(select(func.count(Task.id)).where(
        Task.status == 'done', Task.updated_at >= since))
    return created, completed


def productivity_counts():
    statement = select(Task.user_id, func.count(Task.id),
                       func.sum(case((Task.status == 'done', 1), else_=0)))
    return {user_id: (total, completed) for user_id, total, completed in
            db.session.execute(statement.group_by(Task.user_id))}


def count_high_priority(user_id):
    return db.session.scalar(select(func.count(Task.id)).where(
        Task.user_id == user_id, Task.priority <= HIGH_PRIORITY_LIMIT))


def clear():
    db.session.execute(db.delete(Task))
