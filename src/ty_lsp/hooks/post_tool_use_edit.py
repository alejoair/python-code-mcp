"""
PostToolUse hook para Edit/Write: recarga el archivo en ty y ruff tras una edición.

Después de que Claude aplica un Edit o Write en disco, este hook notifica a los
servidores LSP (via /lsp/reload) para que actualicen su representación interna
del archivo. Sin esto, ty y ruff trabajarían con contenido desactualizado.
"""

import json
import os
import sys
from typing import cast

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
cast("io.TextIOWrapper", sys.stdout).reconfigure(encoding="utf-8")

try:
    import httpx
except ImportError:
    sys.exit(0)

BASE_URL = "http://127.0.0.1:8000"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        sys.exit(0)

    # Notify LSP servers to reload the file from disk
    try:
        httpx.post(
            f"{BASE_URL}/lsp/reload",
            json={"file_path": file_path},
            timeout=5.0,
        )
    except Exception:
        pass

    # No output — silent success


if __name__ == "__main__":
    main()
