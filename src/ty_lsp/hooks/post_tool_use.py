"""
PostToolUse hook: adjunta diagnósticos de tipo y símbolos LSP tras leer un .py.

Recibe JSON por stdin. Si es un Read sobre un .py, consulta al servidor MCP
y escribe en stdout el resumen de tipos y estructura del archivo para que
Claude lo vea como contexto adicional.
"""

import json
import sys

try:
    import httpx
except ImportError:
    sys.exit(0)

SEV_LABEL = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}


def format_output(file_path: str, data: dict) -> str:
    lines = [f"─── ty LSP: {file_path} ───", ""]

    symbols = data.get("symbols", [])
    if symbols:
        lines.append("Symbols:")
        for sym in symbols:
            indent = "    " if sym.get("depth", 0) > 0 else "  "
            lines.append(f"{indent}{sym['kind']} {sym['name']}  line {sym['line']}")
        lines.append("")

    diagnostics = data.get("diagnostics", [])
    if diagnostics:
        lines.append(f"Type diagnostics: {len(diagnostics)} issue(s)")
        for d in diagnostics:
            label = SEV_LABEL.get(d.get("severity", 0), "?")
            lines.append(f"  {label}  line {d['line']}, col {d['col']}: {d['message']}")
    else:
        lines.append("Type diagnostics: ✓ clean")

    return "\n".join(lines)


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
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/file-info",
            json={"file_path": file_path},
            timeout=10.0,
        )
        resp.raise_for_status()
        info = resp.json()
    except Exception:
        sys.exit(0)

    print(format_output(file_path, info))


if __name__ == "__main__":
    main()
