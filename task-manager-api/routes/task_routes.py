from flask import Blueprint
from controllers import task_controller
from middlewares.auth import require_admin

task_bp = Blueprint('tasks', __name__)

task_bp.add_url_rule('/tasks', view_func=task_controller.get_tasks, methods=['GET'])
task_bp.add_url_rule('/tasks/<int:task_id>', view_func=task_controller.get_task, methods=['GET'])
task_bp.add_url_rule('/tasks', view_func=require_admin(task_controller.create_task), methods=['POST'])
task_bp.add_url_rule('/tasks/<int:task_id>', view_func=require_admin(task_controller.update_task), methods=['PUT'])
task_bp.add_url_rule('/tasks/<int:task_id>', view_func=require_admin(task_controller.delete_task), methods=['DELETE'])
task_bp.add_url_rule('/tasks/search', view_func=task_controller.search_tasks, methods=['GET'])
task_bp.add_url_rule('/tasks/stats', view_func=task_controller.task_stats, methods=['GET'])
