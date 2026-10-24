from flask import g

from middlewares.database_context import configure_connection
from controllers.orders import OrderController
from controllers.products import ProductController
from controllers.reports import ReportController
from controllers.system import SystemController
from controllers.users import UserController
from models.database import Database
from models.connection import ConnectionLifecycle
from models.orders import OrderRepository
from models.products import ProductRepository
from models.reports import ReportRepository
from models.system import SystemRepository
from models.users import UserRepository
from routes import orders, products, reports, system, users
from services.orders import OrderService
from services.products import ProductService
from services.reports import ReportService
from services.system import SystemService
from services.users import UserService


def configure_application(app, database=None):
    database = database if database is not None else Database(
        app.config["DATABASE_PATH"], app.config["SEED_PASSWORDS"])
    database.initialize()
    lifecycle = ConnectionLifecycle(database, lambda: g.__dict__)
    configure_connection(app, lifecycle)
    connection = lifecycle.acquire
    product_repository = ProductRepository(connection)
    app.register_blueprint(products.blueprint(ProductController(ProductService(product_repository))))
    app.register_blueprint(users.blueprint(UserController(UserService(UserRepository(connection)))))
    app.register_blueprint(orders.blueprint(OrderController(
        OrderService(OrderRepository(connection), product_repository))))
    app.register_blueprint(reports.blueprint(ReportController(ReportService(ReportRepository(connection)))))
    app.register_blueprint(system.blueprint(SystemController(SystemService(SystemRepository(connection)))))
