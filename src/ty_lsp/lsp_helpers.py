"""Utilidades para formatear respuestas LSP."""

from urllib.parse import unquote, urlparse


def format_location(loc: dict) -> str:
    """Formatea una Location LSP (uri + range) como texto legible."""
    uri = loc.get("uri", "")
    path = uri_to_path(uri)

    range_ = loc.get("range", {})
    start = range_.get("start", {})
    line_num = start.get("line", 0) + 1
    col_num = start.get("character", 0) + 1

    return f"{path}:{line_num}:{col_num}"


def uri_to_path(uri: str) -> str:
    """Convierte un file URI a path del filesystem."""
    path = unquote(urlparse(uri).path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path
