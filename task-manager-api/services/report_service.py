"""Relatórios com consultas agregadas e regras compartilhadas."""
from datetime import timedelta
from constants import PRIORITY_LABELS, RECENT_ACTIVITY_DAYS, VALID_STATUSES
from models import category as category_model, task as task_model, user as user_model
from services.user_service import require_user
from utils.clock import utc_now
from utils.formatting import percentage


def summary():
    now = utc_now()
    counts = task_model.status_counts()
    priorities = task_model.priority_counts()
    overdue = task_model.overdue_tasks(now)
    recent_created, recent_done = task_model.recent_counts(now - timedelta(days=RECENT_ACTIVITY_DAYS))
    productivity = task_model.productivity_counts()
    users = user_model.all_users()
    user_stats = []
    for user in users:
        total, completed = productivity.get(user.id, (0, 0))
        user_stats.append({'user_id': user.id, 'user_name': user.name, 'total_tasks': total,
                           'completed_tasks': completed, 'completion_rate': percentage(completed, total)})
    return {
        'generated_at': str(now),
        'overview': {'total_tasks': sum(counts.values()), 'total_users': len(users),
                     'total_categories': category_model.count()},
        'tasks_by_status': {status: counts.get(status, 0) for status in VALID_STATUSES},
        'tasks_by_priority': {label: priorities.get(priority, 0)
                              for priority, label in PRIORITY_LABELS.items()},
        'overdue': {'count': len(overdue), 'tasks': [
            {'id': task.id, 'title': task.title, 'due_date': str(task.due_date),
             'days_overdue': (now - task.due_date).days} for task in overdue]},
        'recent_activity': {'tasks_created_last_7_days': recent_created,
                            'tasks_completed_last_7_days': recent_done},
        'user_productivity': user_stats,
    }


def for_user(user_id):
    user = require_user(user_id)
    counts = task_model.status_counts(user_id)
    total = sum(counts.values())
    statistics = {'total_tasks': total,
                  **{status: counts.get(status, 0) for status in VALID_STATUSES},
                  'overdue': task_model.count_overdue(utc_now(), user_id),
                  'high_priority': task_model.count_high_priority(user_id),
                  'completion_rate': percentage(counts.get('done', 0), total)}
    return {'user': {'id': user.id, 'name': user.name, 'email': user.email},
            'statistics': statistics}
