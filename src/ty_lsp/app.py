"""Instancia central de FastMCP y estado global del servidor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP  # type: ignore[import-unresolved]

if TYPE_CHECKING:
    from ty_lsp.lsp import TyServer
    from ty_lsp.treesitter import TreeSitterIndex

mcp = FastMCP(
    name="python-code-mcp",
    instructions=(
        "Servidor MCP que expone funcionalidades del type checker ty "
        "via Language Server Protocol. Ty proporciona inferencia de tipos, "
        "diagnósticos y más para archivos Python."
    ),
)

# Estado global accesible por las rutas HTTP custom
ty_server: TyServer | None = None
open_files: dict[str, int] = {}
ts_index: TreeSitterIndex | None = None
