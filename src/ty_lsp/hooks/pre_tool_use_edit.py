"""
PreToolUse hook para Edit/Write: bloquea cambios que introducen errores.

Lee el contenido actual del archivo, simula el cambio (replace para Edit,
contenido nuevo para Write), lo envia a ty via /lsp/check-hypothetical,
y compara diagnosticos antes vs despues. Si hay errores nuevos que
coinciden con la configuracion de bloqueo, retorna decision=block.

Si block-cross-file=true en la config, tambien detecta errores nuevos
en otros archivos del workspace causados por el cambio.

La configuracion de bloqueo se lee desde /lsp/block-mode, que mergea
la config de pyproject.toml con overrides runtime (set_block_mode tool).
"""

from __future__ import annotations

import json
import os
import sys
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
BASE_URL = "http://127.0.0.1:8000"


def _simulate_edit(
    before_content: str, tool_name: str, tool_input: dict
) -> str | None:
    """Construye el contenido simulado tras el edit."""
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


def _uri_to_filename(uri: str) -> str:
    """Extrae el nombre del archivo de una URI file://."""
    path = uri.rsplit("/", 1)[-1] if "/" in uri else uri
    return Path(path).name


def _get_effective_config(file_path: str) -> HookConfig:
    """Obtiene la config efectiva desde el servidor (TOML + runtime override)."""
    with suppress(Exception):
        resp = httpx.post(
            f"{BASE_URL}/lsp/block-mode",
            json={"file_path": file_path},
            timeout=5.0,
        )
        if resp.status_code == HTTP_OK:
            data = resp.json()
            return HookConfig({
                "block-mode": data.get("block_mode", "off"),
                "block-severity": data.get("block_severity", 1),
                "block-rules": data.get("block_rules", []),
                "block-cross-file": data.get("block_cross_file", True),
            })
    # Fallback: leer pyproject.toml directamente
    return HookConfig.from_file(file_path)


def _check_hypothetical(
    file_path: str, content: str, include_workspace: bool
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Llama a /lsp/check-hypothetical y retorna (diags, workspace_diags)."""
    payload: dict = {
        "file_path": file_path,
        "hypothetical_content": content,
    }
    if include_workspace:
        payload["include_workspace"] = True
    with suppress(Exception):
        resp = httpx.post(
            f"{BASE_URL}/lsp/check-hypothetical",
            json=payload,
            timeout=30.0,
        )
        if resp.status_code == HTTP_OK:
            body = resp.json()
            return (
                body.get("diagnostics", []),
                body.get("workspace_diagnostics", {}),
            )
    return [], {}


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

    # Leer configuracion efectiva (pyproject.toml + runtime override)
    hook_config = _get_effective_config(file_path)

    # Asegurar que ty tiene el archivo abierto
    with suppress(Exception):
        httpx.post(
            f"{BASE_URL}/lsp/open",
            json={"file_path": file_path},
            timeout=3.0,
        )

    # Leer contenido actual del archivo
    before_content = ""
    with suppress(Exception):
        before_content = Path(file_path).read_text(encoding="utf-8")
    if not before_content and tool_name == "Edit":
        sys.exit(0)

    # Si el bloqueo esta apagado, salir sin simular
    if not hook_config.blocking_enabled:
        return

    # Construir contenido hipotetico
    hypothetical = _simulate_edit(before_content, tool_name, tool_input)
    if hypothetical is None:
        return

    use_cross_file = hook_config.block_cross_file

    # Diagnosticos BEFORE (contenido actual)
    before_diags, ws_before = _check_hypothetical(
        file_path, before_content, use_cross_file
    )

    # Diagnosticos AFTER (contenido hipotetico)
    after_diags, ws_after = _check_hypothetical(
        file_path, hypothetical, use_cross_file
    )

    # -- Same-file diff ----------------------------------------------

    delta = 0
    edit_start_line = 0
    old_count = 0
    if tool_name == "Edit":
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        old_count = old_string.count("\n")
        new_lines = new_string.count("\n")
        delta = new_lines - old_count
        idx = before_content.find(old_string)
        if idx != -1:
            edit_start_line = before_content[:idx].count("\n") + 1

    before_keys: set[tuple] = set()
    for d in before_diags:
        diag_line = d["line"]
        if (
            tool_name == "Edit"
            and delta != 0
            and diag_line > edit_start_line + old_count
        ):
            diag_line += delta
        before_keys.add(
            _diag_key(d["severity"], diag_line, d["col"], d["message"])
        )

    after_by_key: dict[tuple, dict] = {}
    for d in after_diags:
        k = _diag_key(d["severity"], d["line"], d["col"], d["message"])
        after_by_key[k] = d

    new_same_file = [
        after_by_key[k] for k in set(after_by_key) - before_keys
    ]

    # -- Cross-file diff ---------------------------------------------
    new_cross_file: list[tuple[str, dict]] = []
    if use_cross_file:
        for uri, after_list in ws_after.items():
            before_list = ws_before.get(uri, [])
            before_cf_keys = {
                _diag_key(
                    d["severity"], d["line"], d["col"], d["message"]
                )
                for d in before_list
            }
            for d in after_list:
                k = _diag_key(
                    d["severity"], d["line"], d["col"], d["message"]
                )
                if k not in before_cf_keys:
                    new_cross_file.append((uri, d))

    # -- Filtrar por config de bloqueo ------------------------------
    blocking_same = hook_config.filter_blocking(new_same_file)
    blocking_cross = [
        (uri, d)
        for uri, d in new_cross_file
        if hook_config.should_block_diag(d)
    ]

    if not blocking_same and not blocking_cross:
        return

    # -- BLOQUEAR ----------------------------------------------------
    total = len(blocking_same) + len(blocking_cross)
    block_lines = [
        f"Edit blocked: {total} new issue(s) would be introduced:",
        "",
    ]

    if blocking_same:
        block_lines.append(f"  {Path(file_path).name}:")
        block_lines.extend(
            _format_diag(d)
            for d in sorted(
                blocking_same, key=lambda d: (d["line"], d["col"])
            )
        )

    if blocking_cross:
        by_file: dict[str, list[dict]] = {}
        for uri, d in blocking_cross:
            fname = _uri_to_filename(uri)
            by_file.setdefault(fname, []).append(d)
        for fname, diags in sorted(by_file.items()):
            block_lines.append(f"  {fname} (cross-file):")
            block_lines.extend(
                _format_diag(d)
                for d in sorted(diags, key=lambda d: (d["line"], d["col"]))
            )

    block_lines.append("")
    block_lines.append("Fix the issues before proceeding.")

    result = {"decision": "block", "reason": "\n".join(block_lines)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
