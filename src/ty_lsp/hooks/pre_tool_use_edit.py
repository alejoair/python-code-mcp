"""
PreToolUse hook para Edit/Write: bloquea cambios que introducen errores.

Lee el contenido actual del archivo, simula el cambio (replace para Edit,
contenido nuevo para Write), lo envía a ty via /lsp/check-hypothetical,
y compara diagnósticos antes vs después. Si hay errores nuevos que
coinciden con la configuración de bloqueo, retorna decision=block.

También guarda un snapshot para que el post-hook pueda reportar
información (errores resueltos, impacto cross-file, etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:
    import httpx
except ImportError:
    sys.exit(0)

from ty_lsp.hooks.hook_config import HookConfig

HTTP_OK = 200
SEV_LABEL = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}


def _simulate_edit(before_content: str, tool_name: str, tool_input: dict) -> str | None:
    """Construye el contenido simulado tras el edit. Retorna None si no se puede."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name == "Edit":
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        if not old_string or old_string not in before_content:
            return None
        return before_content.replace(old_string, new_string, 1)
    return None


def _diag_key(severity: int, line: int, col: int, message: str) -> tuple:
    return (severity, line, col, message)


def _format_diag(d: dict) -> str:
    label = SEV_LABEL.get(d.get("severity", 0), "?")
    code = d.get("code", "")
    code_str = f" [{code}]" if code else ""
    return f"  {label}  line {d['line']}, col {d['col']}: {d['message']}{code_str}"


def main() -> None:
    with suppress(Exception):
        data = json.load(sys.stdin)

    try:
        data  # noqa: B018
    except NameError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        sys.exit(0)

    # Leer configuración de hooks
    hook_config = HookConfig.from_file(file_path)

    # Asegurar que ty tiene el archivo abierto
    with suppress(Exception):
        httpx.post(
            "http://127.0.0.1:8000/lsp/open",
            json={"file_path": file_path},
            timeout=3.0,
        )

    # Leer contenido actual del archivo
    before_content = ""
    with suppress(Exception):
        before_content = Path(file_path).read_text(encoding="utf-8")
    if not before_content and tool_name == "Edit":
        sys.exit(0)

    # Obtener diagnósticos BEFORE (contenido real)
    before_diags: list[dict] = []
    with suppress(Exception):
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/file-info",
            json={"file_path": file_path},
            timeout=10.0,
        )
        if resp.status_code == HTTP_OK:
            info = resp.json()
            before_diags = info.get("diagnostics", [])

    # Capturar workspace diagnostics antes (para cross-file del post-hook)
    workspace_before: dict = {}
    with suppress(Exception):
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/workspace-diff",
            json={},
            timeout=30.0,
        )
        if resp.status_code == HTTP_OK:
            workspace_before = resp.json().get("diagnostics_by_file", {})

    # Guardar snapshot para el post-hook
    snapshot = {
        "file_path": file_path,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "before_content": before_content,
        "before_diags": before_diags,
        "workspace_before": workspace_before,
        "hook_config": {
            "block_mode": hook_config.block_mode,
            "block_severity": hook_config.block_severity,
            "block_rules": sorted(hook_config.block_rules),
            "block_cross_file": hook_config.block_cross_file,
        },
    }

    key = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    tmp_path = Path(tempfile.gettempdir()) / f"ty-edit-{key}.json"

    with suppress(Exception), tmp_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)

    # Si el bloqueo está apagado, no simular ni bloquear
    if not hook_config.blocking_enabled:
        return

    # Construir contenido hipotético
    hypothetical = _simulate_edit(before_content, tool_name, tool_input)
    if hypothetical is None:
        return

    # Consultar diagnósticos del contenido simulado
    hypothetical_diags: list[dict] = []
    with suppress(Exception):
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/check-hypothetical",
            json={"file_path": file_path, "hypothetical_content": hypothetical},
            timeout=15.0,
        )
        if resp.status_code == HTTP_OK:
            hypothetical_diags = resp.json().get("diagnostics", [])

    # Calcular errores nuevos
    before_keys = {_diag_key(d["severity"], d["line"], d["col"], d["message"]) for d in before_diags}
    after_by_key: dict[tuple, dict] = {}
    for d in hypothetical_diags:
        k = _diag_key(d["severity"], d["line"], d["col"], d["message"])
        after_by_key[k] = d

    new_keys = set(after_by_key) - before_keys
    new_diags = [after_by_key[k] for k in new_keys]

    # Filtrar por configuración de bloqueo
    blocking = hook_config.filter_blocking(new_diags)

    if not blocking:
        return

    # BLOQUEAR — retornar decision=block
    block_lines = [
        f"Edit blocked: {len(blocking)} new issue(s) would be introduced:",
        "",
        f"  {os.path.basename(file_path)}:",
    ]
    block_lines.extend(_format_diag(d) for d in sorted(blocking, key=lambda d: (d["line"], d["col"])))
    block_lines.append("")
    block_lines.append("Fix the issues before proceeding.")

    result = {
        "decision": "block",
        "reason": "\n".join(block_lines),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
