"""server.py — Entry point del servidor MCP python-code-mcp.

Crea la instancia FastMCP, define el lifespan, y conecta todos los módulos.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.request import url2pathname

from fastmcp import FastMCP  # type: ignore[import-unresolved]

from ty_lsp.app import mcp
from ty_lsp.lsp import RuffServer, TyServer
from ty_lsp.treesitter import TreeSitterIndex
from ty_lsp.validation import open_project_files, parse_gitignore

# Importar módulos de tools y rutas para registrar @mcp.tool y @mcp.custom_route.
import ty_lsp.tools_lsp  # noqa: F401
import ty_lsp.tools_ruff  # noqa: F401
import ty_lsp.tools_search  # noqa: F401
import ty_lsp.tools_treesitter  # noqa: F401
import ty_lsp.routes  # noqa: F401


@asynccontextmanager
async def ty_lifespan(server: FastMCP):
    """Lifespan que inicia y detiene ty y ruff como subprocess LSP."""
    import ty_lsp.app as app

    root_path = Path.cwd()
    root_uri = root_path.as_uri()

    patterns = parse_gitignore(root_path)

    # Iniciar ty (type checker)
    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    open_files = await open_project_files(ty, root_path, patterns)

    # Iniciar ruff (linter + formatter)
    ruff = RuffServer()
    await ruff.start()
    await ruff.initialize(root_uri)

    # Abrir los mismos archivos en ruff
    for uri in open_files:
        file_path_str = _uri_to_path(uri)
        try:
            content = Path(file_path_str).read_text(encoding="utf-8")
            await ruff.open_file(uri, content)
        except OSError:
            pass

    ts_index = TreeSitterIndex()
    ts_index.build(root_path, patterns)

    app.ty_server = ty
    app.ruff_server = ruff
    app.open_files = open_files
    app.ts_index = ts_index

    yield {
        "ty": ty,
        "ruff": ruff,
        "open_files": open_files,
        "ts_index": ts_index,
    }

    await ruff.stop()
    await ty.stop()
    app.ty_server = None
    app.ruff_server = None
    app.open_files = {}
    app.ts_index = None


def _uri_to_path(uri: str) -> str:
    """Convierte un file URI a un path del sistema operativo."""
    # file:///C:/path/to/file.py -> C:/path/to/file.py
    path = uri.replace("file://", "").replace("file:", "")
    path = url2pathname(path)
    # Windows: remover leading slash si hay drive letter (e.g. /C: -> C:)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


# Conectar lifespan a la instancia mcp
mcp.lifespan = ty_lifespan


def main() -> None:
    """Entry point del servidor MCP.

    Sin argumentos: lanza el servidor MCP.
    Con 'install': registra el servidor en Claude Code y sale.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from ty_lsp.install import run_install

        run_install()
        return

    mcp.run(transport="http")


if __name__ == "__main__":
    main()
