"""
server.py — Servidor MCP que expone funcionalidades del type checker ty.

Usa FastMCP con transporte stdio. El servidor ty se maneja internamente
como subprocess via lifespan.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP, Context  # type: ignore[import-unresolved]

from ty_lsp.lsp import TyServer


@asynccontextmanager
async def ty_lifespan(server: FastMCP):
    """Lifespan que inicia y detiene ty server como subprocess."""
    root_path = Path.cwd()
    root_uri = root_path.as_uri()

    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    yield {"ty": ty, "open_files": set[str]()}

    await ty.stop()


mcp = FastMCP(
    name="python-code-mcp",
    instructions=(
        "Servidor MCP que expone funcionalidades del type checker ty "
        "via Language Server Protocol. Ty proporciona inferencia de tipos, "
        "diagnósticos y más para archivos Python."
    ),
    lifespan=ty_lifespan,
)


@mcp.tool
async def hover(
    file_path: str,
    line: int,
    character: int,
    ctx: Context,
) -> str:
    """Obtiene información de tipo (hover) para un símbolo en un archivo Python.

    Args:
        file_path: Path absoluto al archivo Python.
        line: Línea del símbolo (0-indexed).
        character: Columna del símbolo (0-indexed).
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Información de tipo inferido por ty, o un mensaje si no hay info.
    """
    ty: TyServer = ctx.lifespan_context["ty"]
    open_files: set[str] = ctx.lifespan_context["open_files"]

    path = Path(file_path).resolve()
    if not path.exists():
        return f"Error: el archivo no existe: {file_path}"
    if not path.suffix == ".py":
        return f"Error: el archivo no es Python: {file_path}"

    file_uri = path.as_uri()

    # Hacer didOpen solo si el archivo no estaba abierto
    if file_uri not in open_files:
        content = path.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_files.add(file_uri)

    # Solicitar hover
    result = await ty.hover(file_uri, line, character)
    if result is None:
        return "No hay información de hover disponible para esa posición."

    # Extraer el contenido del hover
    contents = result.get("contents")
    if contents is None:
        return "No hay información de hover disponible para esa posición."

    if isinstance(contents, dict):
        value = contents.get("value", "")
        if value:
            return value
        return "No hay información de hover disponible para esa posición."

    if isinstance(contents, str) and contents:
        return contents

    return "No hay información de hover disponible para esa posición."


def main() -> None:
    """Entry point del servidor MCP."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
