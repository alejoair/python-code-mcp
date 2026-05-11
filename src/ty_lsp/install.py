"""
install.py — Script de instalación que registra python-code-mcp como servidor MCP en Claude Code.

Ejecución: python-code-mcp install
"""

import shutil
import subprocess
import sys


def find_claude_cli() -> str | None:
    """Busca el CLI de Claude en el PATH."""
    return shutil.which("claude")


def main() -> None:
    """Registra python-code-mcp como servidor MCP en Claude Code."""
    claude = find_claude_cli()
    if claude is None:
        print("Error: no se encontró el CLI de Claude ('claude').")
        print("Instálalo con: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    url = "http://127.0.0.1:8000/mcp"

    cmd = [
        claude, "mcp", "add",
        "-s", "user",
        "-t", "http",
        "python-code-mcp",
        url,
    ]

    print("Ejecutando: " + " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n[OK] Servidor MCP 'python-code-mcp' registrado exitosamente.")
        print("     Transporte HTTP en " + url)
        print("     Inicia el servidor con: python-code-mcp")
    else:
        print("\n[ERROR] No se pudo registrar el servidor (codigo %d)." % result.returncode)
        sys.exit(result.returncode)


def run_install() -> None:
    """Alias para ser llamado desde server.py."""
    main()


if __name__ == "__main__":
    main()
