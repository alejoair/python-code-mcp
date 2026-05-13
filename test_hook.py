"""Archivo de prueba para verificar hooks de Edit/Write."""


def greet(name: str) -> str:
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    return a + b


result: int = greet("world")
bad = add("not an int", 3)
print(result)
