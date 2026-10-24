from datetime import datetime


def health():
    return {'status': 'ok', 'timestamp': str(datetime.now())}


def index():
    return {'message': 'Task Manager API', 'version': '1.0'}
