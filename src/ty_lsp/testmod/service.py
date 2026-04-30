"""Servicios que operan sobre los modelos."""

from ty_lsp.testmod.models import User, Product
from ty_lsp.testmod.utils import validate_email, format_currency


class UserService:
    """Servicio para gestionar usuarios."""

    def __init__(self) -> None:
        self._users: list[User] = []
        self._next_id = 1

    def create_user(self, name: str, email: str) -> User:
        if not validate_email(email):
            raise ValueError(f"Email inválido: {email}")
        user = User(id=self._next_id, name=name, email=email)
        self._users.append(user)
        self._next_id += 1
        return user

    def get_user(self, user_id: int) -> User | None:
        for user in self._users:
            if user.id == user_id:
                return user
        return None

    def list_users(self) -> list[User]:
        return list(self._users)


class ProductService:
    """Servicio para gestionar productos."""

    def __init__(self) -> None:
        self._products: list[Product] = []

    def add_product(self, name: str, price: float) -> Product:
        product = Product(id=len(self._products) + 1, name=name, price=price)
        self._products.append(product)
        return product

    def get_discounted_price(self, product: Product, discount: float) -> str:
        new_price = product.apply_discount(discount)
        return format_currency(new_price)

    def list_products(self) -> list[Product]:
        return list(self._products)
