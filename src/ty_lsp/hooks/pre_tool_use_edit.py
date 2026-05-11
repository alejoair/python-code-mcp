"""
PreToolUse hook para Edit/Write: captura diagnósticos antes del cambio.

Guarda un snapshot con diagnósticos, contenido y tool_input en un archivo
temporal para que post_tool_use_edit.py pueda comparar antes/después.
"""

import hashlib
import json
import os
import sys
import tempfile

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:
    import httpx
except ImportError:
    sys.exit(0)


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

    # Asegurar que ty tiene el archivo abierto
    try:
        httpx.post(
            "http://127.0.0.1:8000/lsp/open",
            json={"file_path": file_path},
            timeout=3.0,
        )
    except Exception:
        pass  # servidor no activo

    # Obtener diagnósticos actuales (antes del cambio)
    diagnostics = []
    before_content = ""
    try:
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/file-info",
            json={"file_path": file_path},
            timeout=10.0,
        )
        if resp.status_code == 200:
            info = resp.json()
            diagnostics = info.get("diagnostics", [])
    except Exception:
        pass

    # Leer contenido antes del cambio (para remapeo de líneas)
    try:
        before_content = open(file_path, encoding="utf-8").read()
    except Exception:
        pass

    # Capturar diagnósticos de todo el workspace (para detección cross-file)
    workspace_diagnostics: dict = {}
    try:
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/workspace-diff",
            json={},
            timeout=30.0,
        )
        if resp.status_code == 200:
            workspace_diagnostics = resp.json().get("diagnostics_by_file", {})
    except Exception:
        pass

    # Guardar snapshot en archivo temporal
    snapshot = {
        "file_path": file_path,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "before_content": before_content,
        "diagnostics": diagnostics,
        "workspace_diagnostics": workspace_diagnostics,
    }

    key = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    tmp_path = os.path.join(tempfile.gettempdir(), f"ty-edit-{key}.json")

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
    except Exception:
        pass

    # Silencioso — no imprimir nada


if __name__ == "__main__":
    main()
