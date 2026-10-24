from errors import ValidationError


class OrderService:
    def __init__(self, orders, products):
        self.orders = orders
        self.products = products

    def create(self, user_id, items):
        with self.orders.transaction() as connection:
            products = self.products.find_many(dict.fromkeys(item["produto_id"] for item in items), connection)
            quantities, total = {}, 0
            for item in items:
                product_id, quantity = item["produto_id"], item["quantidade"]
                product = products.get(product_id)
                if product is None:
                    raise ValidationError("Produto " + str(product_id) + " não encontrado", False)
                quantities[product_id] = quantities.get(product_id, 0) + quantity
                if product["estoque"] < quantities[product_id]:
                    raise ValidationError("Estoque insuficiente para " + product["nome"], False)
                total += product["preco"] * quantity
            order_id = self.orders.insert(user_id, total, connection)
            for item in items:
                product_id, quantity = item["produto_id"], item["quantidade"]
                self.orders.insert_item(order_id, product_id, quantity, products[product_id]["preco"], connection)
                self.products.decrement_stock(product_id, quantity, connection)
        return {"pedido_id": order_id, "total": total}

    def list(self, user_id=None):
        return self.orders.list(user_id)

    def update_status(self, order_id, status):
        self.orders.update_status(order_id, status)
