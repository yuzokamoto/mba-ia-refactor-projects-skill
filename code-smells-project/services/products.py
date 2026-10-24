from errors import NotFoundError


class ProductService:
    def __init__(self, products):
        self.products = products

    def require(self, product_id, success=None):
        product = self.products.find(product_id)
        if product is None:
            raise NotFoundError("Produto não encontrado", success)
        return product

    def all(self):
        return self.products.all()

    def create(self, data):
        return self.products.create(data)

    def update(self, product_id, data):
        self.products.update(product_id, data)

    def delete(self, product_id):
        self.require(product_id)
        self.products.delete(product_id)

    def search(self, term, category, minimum, maximum):
        return self.products.search(term, category, minimum, maximum)
