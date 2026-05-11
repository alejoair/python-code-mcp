"""Extracción de símbolos de archivos Python usando ast."""

import ast


def extract_symbols(source: str) -> list[dict]:
    """Extrae clases y funciones de un archivo Python usando ast (2 niveles)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    symbols: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno, "depth": 0})
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    symbols.append({"kind": kind, "name": child.name, "line": child.lineno, "depth": 1})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            symbols.append({"kind": kind, "name": node.name, "line": node.lineno, "depth": 0})
    return symbols
