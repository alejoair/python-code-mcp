"""Punto de entrada que usa todo el módulo."""

from ty_lsp.testmod.service import UserService, ProductService
from ty_lsp.testmod.utils import format_currency

user_svc = UserService()
user_svc.create_user("Alice", "alice@example.com")
user_svc.create_user("Bob", "bob@example.com")

product_svc = ProductService()
laptop = product_svc.add_product("Laptop", 1299.99)
mouse = product_svc.add_product("Mouse", 29.99)

# Usar funciones cross-file
price = product_svc.get_discounted_price(laptop, 15)
formatted = format_currency(laptop.price)

print(price)
print(formatted)
