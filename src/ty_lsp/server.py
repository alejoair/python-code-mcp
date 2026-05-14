"""server.py — Entry point del servidor MCP python-code-mcp.

Importa la instancia FastMCP (con lifespan) desde app.py y registra
todos los módulos de tools y rutas como side-effects.
"""

import sys

from ty_lsp.app import mcp

# Importar módulos de tools y rutas para registrar @mcp.tool y @mcp.custom_route.
import ty_lsp.tools_lsp  # noqa: F401
import ty_lsp.tools_ruff  # noqa: F401
import ty_lsp.tools_search  # noqa: F401
import ty_lsp.tools_treesitter  # noqa: F401
import ty_lsp.routes  # noqa: F401


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
