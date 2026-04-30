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

    server_cmd = "python-code-mcp"

    # Verificar que el servidor está instalado
    if shutil.which(server_cmd) is None:
        print("Error: no se encontró el comando '" + server_cmd + "'.")
        print("Verifica que python-code-mcp esté instalado: pip install python-code-mcp")
        sys.exit(1)

    cmd = [
        claude, "mcp", "add",
        "-s", "user",
        "-t", "stdio",
        "python-code-mcp",
        "--", server_cmd,
    ]

    print("Ejecutando: " + " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n[OK] Servidor MCP 'python-code-mcp' registrado exitosamente.")
        print("     Transporte stdio, alcance user (global).")
    else:
        print("\n[ERROR] No se pudo registrar el servidor (codigo %d)." % result.returncode)
        sys.exit(result.returncode)


def run_install() -> None:
    """Alias para ser llamado desde server.py."""
    main()


if __name__ == "__main__":
    main()
