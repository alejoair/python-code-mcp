"""
PostToolUse hook para Edit/Write: compara diagnósticos antes/después.

Carga el snapshot del pre-hook, recarga el archivo en ty, obtiene
diagnósticos nuevos y muestra solo los errores introducidos por el edit.
Remapea números de línea para compensar inserciones/eliminaciones.
"""

import hashlib
import json
import os
import sys
import tempfile

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8")

try:
    import httpx
except ImportError:
    sys.exit(0)

SEV_LABEL = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}


def _remap_line(line: int, start_line: int, old_count: int, delta: int) -> int:
    """Ajusta un número de línea según el offset del edit.

    Solo ajusta líneas que están DESPUÉS del bloque editado.
    Líneas dentro o antes del bloque no se mueven.
    """
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
    """Crea una clave comparable para un diagnóstico."""
    return (severity, line, col, message)


def _format_diag(d: dict) -> str:
    """Formatea un diagnóstico para output."""
    label = SEV_LABEL.get(d.get("severity", 0), "?")
    return f"  {label}  line {d['line']}, col {d['col']}: {d['message']}"


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

    # Cargar snapshot del pre-hook
    key = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    tmp_path = os.path.join(tempfile.gettempdir(), f"ty-edit-{key}.json")

    try:
        with open(tmp_path, encoding="utf-8") as f:
            snapshot = json.load(f)
    except Exception:
        sys.exit(0)

    before_diags = snapshot.get("diagnostics", [])
    before_content = snapshot.get("before_content", "")
    saved_tool_name = snapshot.get("tool_name", "")
    saved_tool_input = snapshot.get("tool_input", {})

    # Recargar archivo en ty (didChange)
    try:
        httpx.post(
            "http://127.0.0.1:8000/lsp/reload",
            json={"file_path": file_path},
            timeout=5.0,
        )
    except Exception:
        pass

    # Obtener diagnósticos después del cambio
    after_diags = []
    try:
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/file-info",
            json={"file_path": file_path},
            timeout=10.0,
        )
        if resp.status_code == 200:
            info = resp.json()
            after_diags = info.get("diagnostics", [])
    except Exception:
        sys.exit(0)

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
    after_keys = set()
    after_by_key = {}
    for d in after_diags:
        k = _diag_key(d["severity"], d["line"], d["col"], d["message"])
        after_keys.add(k)
        after_by_key[k] = d

    # Nuevos errores: están en after pero no en before (remapeado)
    new_keys = after_keys - remapped_before
    new_diags = [after_by_key[k] for k in new_keys]

    # Errores resueltos: están en before (remapeado) pero no en after
    resolved_keys = remapped_before - after_keys
    resolved_diags = []
    for d in before_diags:
        adj_line = d["line"]
        if saved_tool_name == "Edit" and delta != 0:
            adj_line = _remap_line(d["line"], start_line, old_count, delta)
        k = _diag_key(d["severity"], adj_line, d["col"], d["message"])
        if k in resolved_keys:
            resolved_diags.append({"severity": d["severity"], "line": adj_line, "col": d["col"], "message": d["message"]})

    # Formatear output
    basename = os.path.basename(file_path)
    lines = [f"--- ty type check: {basename} ---", ""]

    pre_existing = len(after_diags) - len(new_diags)

    if not after_diags:
        lines.append("No type errors. File is clean.")
    elif new_diags:
        lines.append(f"NEW issues introduced by this edit: {len(new_diags)}")
        for d in sorted(new_diags, key=lambda d: (d["line"], d["col"])):
            lines.append(_format_diag(d))
        if pre_existing > 0:
            lines.append("")
            lines.append(f"  ({pre_existing} pre-existing issue(s) not shown)")
    else:
        lines.append(f"No new issues. ({pre_existing} pre-existing)")

    if resolved_diags:
        lines.append("")
        lines.append(f"Resolved by this edit: {len(resolved_diags)}")
        for d in sorted(resolved_diags, key=lambda d: (d["line"], d["col"])):
            lines.append(_format_diag(d))

    # --- Cross-file diagnostics ---
    workspace_before = snapshot.get("workspace_diagnostics", {})
    workspace_after: dict = {}
    try:
        resp = httpx.post(
            "http://127.0.0.1:8000/lsp/workspace-diff",
            json={},
            timeout=30.0,
        )
        if resp.status_code == 200:
            workspace_after = resp.json().get("diagnostics_by_file", {})
    except Exception:
        pass

    if workspace_after:
        from pathlib import Path
        edited_uri = Path(file_path).resolve().as_uri()
        cross_lines: list[str] = []
        total_cross = 0
        affected_files = 0

        for uri, after_file_diags in workspace_after.items():
            if uri == edited_uri:
                continue
            if not after_file_diags:
                continue

            before_file_diags = workspace_before.get(uri, [])
            before_keys = set(
                _diag_key(d["severity"], d["line"], d["col"], d["message"])
                for d in before_file_diags
            )
            after_keys = set(
                _diag_key(d["severity"], d["line"], d["col"], d["message"])
                for d in after_file_diags
            )
            new_cross = after_keys - before_keys
            if not new_cross:
                continue

            affected_files += 1
            # Convertir URI a path legible
            path = uri
            if path.startswith("file:///"):
                from urllib.parse import unquote
                path = unquote(path[8:])
                if len(path) > 1 and path[1] == ":":
                    pass  # Windows path ya correcto
            cross_lines.append(f"\n  {path}:")
            for k in sorted(new_cross):
                total_cross += 1
                cross_lines.append(f"    {SEV_LABEL.get(k[0], '?')}  line {k[1]}, col {k[2]}: {k[3]}")

        if cross_lines:
            lines.append("")
            lines.append(f"Cross-file impact: {total_cross} new issue(s) in {affected_files} other file(s):")
            lines.extend(cross_lines)

    output_text = "\n".join(lines)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": output_text,
        }
    }
    print(json.dumps(result))

    # Limpiar snapshot temporal
    try:
        os.remove(tmp_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
