"""Rutas HTTP personalizadas para los hooks de Claude Code."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

import ty_lsp.app as app
from ty_lsp.app import mcp
from ty_lsp.ast_extract import extract_symbols


@mcp.custom_route("/lsp/open", methods=["POST"])
async def lsp_open(request: Request) -> JSONResponse:
    """Abre un archivo .py en ty y ruff (warm-up para hooks PreToolUse)."""
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON inválido"}, status_code=400)

    file_path = body.get("file_path", "")
    path = Path(file_path).resolve()

    if not path.exists() or path.suffix != ".py" or not _is_project_file(path):
        return JSONResponse({"ok": True})

    file_uri = path.as_uri()
    if file_uri not in app.open_files:
        content = path.read_text(encoding="utf-8")
        await app.ty_server.open_file(file_uri, content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, content)
        app.open_files[file_uri] = 1

    return JSONResponse({"ok": True})


@mcp.custom_route("/lsp/file-info", methods=["POST"])
async def lsp_file_info(request: Request) -> JSONResponse:
    """Retorna diagnósticos de tipo (ty) y símbolos de un archivo .py."""
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON inválido"}, status_code=400)

    file_path = body.get("file_path", "")
    path = Path(file_path).resolve()

    if not path.exists() or path.suffix != ".py":
        return JSONResponse({"error": f"archivo inválido: {file_path}"}, status_code=400)

    if not _is_project_file(path):
        return JSONResponse({"diagnostics": [], "symbols": []})

    file_uri = path.as_uri()
    content = path.read_text(encoding="utf-8")

    if file_uri not in app.open_files:
        await app.ty_server.open_file(file_uri, content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, content)
        app.open_files[file_uri] = 1

    raw_diags = await app.ty_server.diagnostic(file_uri)
    diagnostics = _simplify_diags(raw_diags, source="ty")
    if app.ruff_server is not None:
        diagnostics.extend(_simplify_diags(await app.ruff_server.diagnostic(file_uri), source="ruff"))

    symbols = extract_symbols(content)

    return JSONResponse({"diagnostics": diagnostics, "symbols": symbols})


@mcp.custom_route("/lsp/reload", methods=["POST"])
async def lsp_reload(request: Request) -> JSONResponse:
    """Recarga un .py en ty y ruff post-edición (didChange + didOpen fallback)."""
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON inválido"}, status_code=400)

    file_path = body.get("file_path", "")
    path = Path(file_path).resolve()

    if not path.exists() or path.suffix != ".py":
        return JSONResponse({"error": f"archivo inválido: {file_path}"}, status_code=400)

    file_uri = path.as_uri()
    content = path.read_text(encoding="utf-8")

    if file_uri in app.open_files:
        version = app.open_files[file_uri] + 1
        await app.ty_server.change_file(file_uri, content, version)
        if app.ruff_server is not None:
            await app.ruff_server.change_file(file_uri, content, version)
        app.open_files[file_uri] = version
    else:
        await app.ty_server.open_file(file_uri, content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, content)
        app.open_files[file_uri] = 1

    if app.ts_index is not None:
        app.ts_index.reindex_file(str(path))

    return JSONResponse({"ok": True})


def _is_project_file(path: Path) -> bool:
    """Check if a file is inside the project root (cwd) and not in .claude/."""
    try:
        rel = path.relative_to(Path.cwd())
    except ValueError:
        return False
    parts = rel.parts
    return ".claude" not in parts


def _simplify_diags(raw_diags: list[dict], source: str = "ty") -> list[dict]:
    """Convierte diagnósticos LSP crudos al formato simplificado."""
    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    return [
        {
            "severity": sev_map.get(d.get("severity", 0), 0),
            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
            "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
            "code": (d.get("code") or "") if isinstance(d.get("code"), str) else str(d.get("code", "")),
            "message": d.get("message", ""),
            "source": source,
        }
        for d in raw_diags
    ]


async def _collect_workspace_diags(exclude_uri: str) -> dict[str, list[dict]]:
    """Consulta diagnósticos de todos los archivos abiertos excepto uno."""
    if app.ty_server is None:
        return {}
    result: dict[str, list[dict]] = {}
    for uri in list(app.open_files):
        if uri == exclude_uri:
            continue
        ty_diags = await app.ty_server.diagnostic(uri)
        simplified = _simplify_diags(ty_diags, source="ty")
        if app.ruff_server is not None:
            simplified.extend(_simplify_diags(await app.ruff_server.diagnostic(uri), source="ruff"))
        if simplified:
            result[uri] = simplified
    return result


@mcp.custom_route("/lsp/check-hypothetical", methods=["POST"])
async def lsp_check_hypothetical(request: Request) -> JSONResponse:
    """Diagnostica contenido hipotético sin persistirlo en disco.

    Acepta file_path + hypothetical_content, envía el contenido simulado
    a ty via didChange, obtiene diagnósticos, y restaura el contenido original.

    Si include_workspace=true, también consulta diagnósticos de los demás
    archivos abiertos mientras el contenido hipotético está activo, para
    detectar errores cross-file antes de que se aplique el cambio.

    Usado por el pre-hook para decidir si bloquear un edit ANTES de aplicarlo.
    """
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON inválido"}, status_code=400)

    file_path = body.get("file_path", "")
    hypothetical_content = body.get("hypothetical_content", "")
    include_workspace = body.get("include_workspace", False)
    path = Path(file_path).resolve()

    if path.suffix != ".py":
        return JSONResponse({"error": f"archivo inválido: {file_path}"}, status_code=400)

    file_uri = path.as_uri()
    is_new_file = not path.exists()

    # Contenido real para restaurar al final
    real_content: str | None = None
    if not is_new_file:
        real_content = path.read_text(encoding="utf-8")

    if is_new_file:
        # Archivo nuevo (Write): abrir directamente con contenido hipotético
        await app.ty_server.open_file(file_uri, hypothetical_content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, hypothetical_content)
        app.open_files[file_uri] = 1

        # Obtener diagnósticos del archivo
        diagnostics = _simplify_diags(await app.ty_server.diagnostic(file_uri), source="ty")
        if app.ruff_server is not None:
            diagnostics.extend(_simplify_diags(await app.ruff_server.diagnostic(file_uri), source="ruff"))

        # Diagnósticos cross-file (mientras el archivo hipotético está abierto)
        workspace_diags: dict[str, list[dict]] = {}
        if include_workspace:
            workspace_diags = await _collect_workspace_diags(file_uri)

        # Cerrar el archivo ficticio para no dejar estado basura
        await app.ty_server.close_file(file_uri)
        if app.ruff_server is not None:
            await app.ruff_server.close_file(file_uri)
        del app.open_files[file_uri]
    else:
        # Archivo existente (Edit): abrir si no lo está, simular cambio, restaurar
        assert real_content is not None  # guaranteed by not is_new_file
        if file_uri not in app.open_files:
            await app.ty_server.open_file(file_uri, real_content)  # type: ignore[arg-type]
            if app.ruff_server is not None:
                await app.ruff_server.open_file(file_uri, real_content)  # type: ignore[arg-type]
            app.open_files[file_uri] = 1

        current_version = app.open_files[file_uri]
        hypothetical_version = current_version + 1

        # Mandar contenido hipotético a ty
        await app.ty_server.change_file(file_uri, hypothetical_content, hypothetical_version)
        if app.ruff_server is not None:
            await app.ruff_server.change_file(file_uri, hypothetical_content, hypothetical_version)

        # Obtener diagnósticos del contenido hipotético
        diagnostics = _simplify_diags(await app.ty_server.diagnostic(file_uri), source="ty")
        if app.ruff_server is not None:
            diagnostics.extend(_simplify_diags(await app.ruff_server.diagnostic(file_uri), source="ruff"))

        # Diagnósticos cross-file (mientras el contenido hipotético está activo)
        workspace_diags = {}
        if include_workspace:
            workspace_diags = await _collect_workspace_diags(file_uri)

        # Restaurar contenido real en ty
        restore_version = hypothetical_version + 1
        await app.ty_server.change_file(file_uri, real_content, restore_version)  # type: ignore[arg-type]
        if app.ruff_server is not None:
            await app.ruff_server.change_file(file_uri, real_content, restore_version)  # type: ignore[arg-type]
        app.open_files[file_uri] = restore_version

    response: dict = {"diagnostics": diagnostics}
    if include_workspace:
        response["workspace_diagnostics"] = workspace_diags
    return JSONResponse(response)


@mcp.custom_route("/lsp/workspace-diff", methods=["POST"])
async def lsp_workspace_diff(_request: Request) -> JSONResponse:
    """Retorna diagnósticos de todo el workspace agrupados por archivo.

    Usa textDocument/diagnostic por cada archivo abierto (pull model)
    en vez de publishDiagnostics (push) para garantizar resultados frescos.
    """
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    result: dict[str, list[dict]] = {}
    for uri in app.open_files:
        ty_diags = await app.ty_server.diagnostic(uri)
        simplified = _simplify_diags(ty_diags, source="ty")
        if app.ruff_server is not None:
            simplified.extend(_simplify_diags(await app.ruff_server.diagnostic(uri), source="ruff"))
        if simplified:
            result[uri] = simplified

    return JSONResponse({"diagnostics_by_file": result})


def _find_pyproject(file_path: str) -> Path | None:
    """Busca pyproject.toml subiendo desde el directorio del archivo."""
    start = Path(file_path).resolve().parent
    for parent in [start, *start.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            return candidate
    return None


@mcp.custom_route("/lsp/block-mode", methods=["POST"])
async def lsp_block_mode(request: Request) -> JSONResponse:
    """Retorna la configuración efectiva de bloqueo.

    Lee la config base de pyproject.toml y aplica el override runtime
    (seteado via la tool set_block_mode). Los hooks consultan este
    endpoint para saber la config actual sin parsear TOML ellos mismos.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    file_path = body.get("file_path", "")

    # Leer config base de pyproject.toml
    base_config: dict = {}
    with suppress(Exception):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redefine]

        toml_path = _find_pyproject(file_path)
        if toml_path is not None:
            with toml_path.open("rb") as f:
                config = tomllib.load(f)
            base_config = (
                config.get("tool", {})
                .get("python-code-mcp", {})
                .get("hooks", {})
            )

    # Aplicar override runtime
    override = app.block_mode_override or {}
    effective = {
        "block_mode": override.get(
            "block_mode", base_config.get("block-mode", "off")
        ),
        "block_severity": override.get(
            "block_severity", base_config.get("block-severity", 1)
        ),
        "block_rules": base_config.get("block-rules", []),
        "block_cross_file": base_config.get("block-cross-file", True),
    }

    return JSONResponse(effective)
