"""
PostToolUse hook para Edit/Write: reporta diagnósticos informativos.

Carga el snapshot del pre-hook, recarga el archivo en ty, compara
diagnósticos antes/después con remapeo de líneas, y muestra solo
los errores nuevos, resueltos e impacto cross-file.

El bloqueo real ocurre en el pre-hook (pre_tool_use_edit.py).
Este hook es puramente informativo.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8")

try:
    import httpx
except ImportError:
    sys.exit(0)

SEV_LABEL = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}
HTTP_OK = 200


def _remap_line(line: int, start_line: int, old_count: int, delta: int) -> int:
    """Ajusta un número de línea según el offset del edit."""
    if line > start_line + old_count:
        return line + delta
    return line


def _find_old_string_line(before_content: str, old_string: str) -> int | None:
    """Encuentra la línea (1-indexed) donde empieza old_string en el contenido."""
    idx = before_content.find(old_string)
    if idx == -1:
        return None
    return before_content[:idx].count("\n") + 1


def _diag_key(severity: int, line: int, col: int, message: str) -> tuple:
    return (severity, line, col, message)


def _format_diag(d: dict) -> str:
    label = SEV_LABEL.get(d.get("severity", 0), "?")
    code = d.get("code", "")
    code_str = f" [{code}]" if code else ""
    return f"  {label}  line {d['line']}, col {d['col']}: {d['message']}{code_str}"


def _collect_cross_file(
    workspace_before: dict,
    workspace_after: dict,
    edited_uri: str,
) -> tuple[list[str], int, int]:
    """Recolecta diagnósticos cross-file nuevos (informativo).

    Returns:
        (cross_lines, total_cross, affected_files)
    """
    cross_lines: list[str] = []
    total_cross = 0
    affected_files = 0

    for uri, after_file_diags in workspace_after.items():
        if uri == edited_uri or not after_file_diags:
            continue

        before_file_diags = workspace_before.get(uri, [])
        before_file_keys = {
            _diag_key(d["severity"], d["line"], d["col"], d["message"]) for d in before_file_diags
        }
        after_file_keys = {
            _diag_key(d["severity"], d["line"], d["col"], d["message"]) for d in after_file_diags
        }
        new_cross = after_file_keys - before_file_keys
        if not new_cross:
            continue

        affected_files += 1
        path = uri
        if path.startswith("file:///"):
            path = unquote(path[8:])

        cross_lines.append(f"\n  {path}:")
        for k in sorted(new_cross):
            total_cross += 1
            cross_lines.append(
                f"    {SEV_LABEL.get(k[0], '?')}  line {k[1]}, col {k[2]}: {k[3]}"
            )

    return cross_lines, total_cross, affected_files


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

    # Cargar snapshot del pre-hook
    key = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    tmp_path = Path(tempfile.gettempdir()) / f"ty-edit-{key}.json"

    snapshot = {}
    with suppress(Exception), tmp_path.open(encoding="utf-8") as f:
        snapshot = json.load(f)

    if not snapshot:
        sys.exit(0)

    before_diags = snapshot.get("before_diags", [])
    before_content = snapshot.get("before_content", "")
    saved_tool_name = snapshot.get("tool_name", "")
    saved_tool_input = snapshot.get("tool_input", {})

    # Recargar archivo en ty (didChange)
    with suppress(Exception):
        httpx.post(
            "http://127.0.0.1:8000/lsp/reload",
            json={"file_path": file_path},
            timeout=5.0,
        )

    # Obtener diagnósticos después del cambio
    after_diags: list[dict] = []
    with suppress(Exception):
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/file-info",
            json={"file_path": file_path},
            timeout=10.0,
        )
        if resp.status_code == HTTP_OK:
            info = resp.json()
            after_diags = info.get("diagnostics", [])

    # Calcular parámetros de remapeo para Edit
    delta = 0
    start_line = 0
    old_count = 0

    if saved_tool_name == "Edit":
        old_string = saved_tool_input.get("old_string", "")
        new_string = saved_tool_input.get("new_string", "")

        if old_string and before_content:
            found_line = _find_old_string_line(before_content, old_string)
            if found_line is not None:
                start_line = found_line
                old_count = old_string.count("\n")
                new_lines = new_string.count("\n")
                delta = new_lines - old_count

    # Remapear diagnósticos before para que sean comparables con after
    remapped_before = set()
    for d in before_diags:
        adj_line = d["line"]
        if saved_tool_name == "Edit" and delta != 0:
            adj_line = _remap_line(d["line"], start_line, old_count, delta)
        remapped_before.add(_diag_key(d["severity"], adj_line, d["col"], d["message"]))

    # Claves de diagnósticos after
    after_by_key: dict[tuple, dict] = {}
    for d in after_diags:
        k = _diag_key(d["severity"], d["line"], d["col"], d["message"])
        after_by_key[k] = d

    # Nuevos errores
    new_keys = set(after_by_key) - remapped_before
    new_diags = [after_by_key[k] for k in new_keys]

    # Errores resueltos
    resolved_keys = remapped_before - set(after_by_key)
    resolved_diags = []
    for d in before_diags:
        adj_line = d["line"]
        if saved_tool_name == "Edit" and delta != 0:
            adj_line = _remap_line(d["line"], start_line, old_count, delta)
        k = _diag_key(d["severity"], adj_line, d["col"], d["message"])
        if k in resolved_keys:
            resolved_diags.append(
                {"severity": d["severity"], "line": adj_line, "col": d["col"], "message": d["message"]}
            )

    # --- Cross-file diagnostics ---
    workspace_before = snapshot.get("workspace_before", {})
    workspace_after: dict = {}
    with suppress(Exception):
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/workspace-diff",
            json={},
            timeout=30.0,
        )
        if resp.status_code == HTTP_OK:
            workspace_after = resp.json().get("diagnostics_by_file", {})

    edited_uri = Path(file_path).resolve().as_uri()
    cross_file_lines, total_cross, affected_files = _collect_cross_file(
        workspace_before, workspace_after, edited_uri
    )

    # Limpiar snapshot temporal
    with suppress(Exception):
        tmp_path.unlink()

    # --- Formatear output informativo ---
    basename = os.path.basename(file_path)
    lines = [f"--- ty type check: {basename} ---", ""]

    pre_existing = len(after_diags) - len(new_diags)

    if not after_diags:
        lines.append("No type errors. File is clean.")
    elif new_diags:
        lines.append(f"NEW issues introduced by this edit: {len(new_diags)}")
        lines.extend(_format_diag(d) for d in sorted(new_diags, key=lambda d: (d["line"], d["col"])))
        if pre_existing > 0:
            lines.append("")
            lines.append(f"  ({pre_existing} pre-existing issue(s) not shown)")
    else:
        lines.append(f"No new issues. ({pre_existing} pre-existing)")

    if resolved_diags:
        lines.append("")
        lines.append(f"Resolved by this edit: {len(resolved_diags)}")
        lines.extend(_format_diag(d) for d in sorted(resolved_diags, key=lambda d: (d["line"], d["col"])))

    if cross_file_lines:
        lines.append("")
        lines.append(f"Cross-file impact: {total_cross} new issue(s) in {affected_files} other file(s):")
        lines.extend(cross_file_lines)

    output_text = "\n".join(lines)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": output_text,
        }
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
