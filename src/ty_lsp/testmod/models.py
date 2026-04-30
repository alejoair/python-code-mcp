"""Modelos de datos del módulo de prueba."""


class User:
    """Representa un usuario del sistema."""

    def __init__(self, id: int, name: str, email: str) -> None:
        self.id = id
        self.name = name
        self.email = email

    def greet(self) -> str:
        return f"Hello, {self.name}!"

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r})"


class Product:
    """Representa un producto en el catálogo."""

    def __init__(self, id: int, name: str, price: float) -> None:
        self.id = id
        self.name = name
        self.price = price

    def apply_discount(self, percent: float) -> float:
        """Aplica un descuento y retorna el nuevo precio."""
        factor = 1.0 - percent / 100.0
        return self.price * factor

    def __repr__(self) -> str:
        return f"Product(id={self.id}, name={self.name!r}, price={self.price})"
