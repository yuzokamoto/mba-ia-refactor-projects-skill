from flask import Blueprint
from controllers import system_controller

system_bp = Blueprint('system', __name__)

system_bp.add_url_rule('/health', view_func=system_controller.health, methods=['GET'])
system_bp.add_url_rule('/', view_func=system_controller.index, methods=['GET'])
