"""
PreToolUse hook: abre el archivo .py en ty antes de que Claude lo lea.

Recibe JSON por stdin con el contexto del tool call. Si es un Read sobre
un .py, notifica al servidor MCP para que lo precargue en ty (warm-up).
"""

import json
import sys

try:
    import httpx
except ImportError:
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Read":
        sys.exit(0)

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        sys.exit(0)

    try:
        httpx.post(
            "http://127.0.0.1:8000/lsp/open",
            json={"file_path": file_path},
            timeout=3.0,
        )
    except Exception:
        pass  # servidor no activo, ignorar silenciosamente


if __name__ == "__main__":
    main()
