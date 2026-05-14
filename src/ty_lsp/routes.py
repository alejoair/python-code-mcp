"""Rutas HTTP personalizadas para los hooks de Claude Code."""

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

    if not path.exists() or path.suffix != ".py":
        return JSONResponse({"error": f"archivo inválido: {file_path}"}, status_code=400)

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

    file_uri = path.as_uri()
    content = path.read_text(encoding="utf-8")

    if file_uri not in app.open_files:
        await app.ty_server.open_file(file_uri, content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, content)
        app.open_files[file_uri] = 1

    raw_diags = await app.ty_server.diagnostic(file_uri)
    if app.ruff_server is not None:
        raw_diags.extend(await app.ruff_server.diagnostic(file_uri))
    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    diagnostics = [
        {
            "severity": sev_map.get(d.get("severity", 0), 0),
            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
            "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
            "code": (d.get("code") or "") if isinstance(d.get("code"), str) else str(d.get("code", "")),
            "message": d.get("message", ""),
        }
        for d in raw_diags
    ]

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


@mcp.custom_route("/lsp/check-hypothetical", methods=["POST"])
async def lsp_check_hypothetical(request: Request) -> JSONResponse:
    """Diagnostica contenido hipotético sin persistirlo en disco.

    Acepta file_path + hypothetical_content, envía el contenido simulado
    a ty via didChange, obtiene diagnósticos, y restaura el contenido original.

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
    path = Path(file_path).resolve()

    if path.suffix != ".py":
        return JSONResponse({"error": f"archivo inválido: {file_path}"}, status_code=400)

    file_uri = path.as_uri()
    is_new_file = not path.exists()

    if is_new_file:
        # Archivo nuevo (Write): abrir directamente con contenido hipotético
        await app.ty_server.open_file(file_uri, hypothetical_content)
        if app.ruff_server is not None:
            await app.ruff_server.open_file(file_uri, hypothetical_content)
        app.open_files[file_uri] = 1

        # Obtener diagnósticos
        raw_diags = await app.ty_server.diagnostic(file_uri)
        if app.ruff_server is not None:
            raw_diags.extend(await app.ruff_server.diagnostic(file_uri))

        # Cerrar el archivo ficticio para no dejar estado basura
        await app.ty_server.close_file(file_uri)
        if app.ruff_server is not None:
            await app.ruff_server.close_file(file_uri)
        del app.open_files[file_uri]
    else:
        # Archivo existente (Edit): abrir si no lo está, simular cambio, restaurar
        if file_uri not in app.open_files:
            real_content = path.read_text(encoding="utf-8")
            await app.ty_server.open_file(file_uri, real_content)
            if app.ruff_server is not None:
                await app.ruff_server.open_file(file_uri, real_content)
            app.open_files[file_uri] = 1

        current_version = app.open_files[file_uri]
        hypothetical_version = current_version + 1

        # Mandar contenido hipotético a ty
        await app.ty_server.change_file(file_uri, hypothetical_content, hypothetical_version)
        if app.ruff_server is not None:
            await app.ruff_server.change_file(file_uri, hypothetical_content, hypothetical_version)

        # Obtener diagnósticos del contenido hipotético
        raw_diags = await app.ty_server.diagnostic(file_uri)
        if app.ruff_server is not None:
            raw_diags.extend(await app.ruff_server.diagnostic(file_uri))

        # Restaurar contenido real en ty
        restore_version = hypothetical_version + 1
        real_content = path.read_text(encoding="utf-8")
        await app.ty_server.change_file(file_uri, real_content, restore_version)
        if app.ruff_server is not None:
            await app.ruff_server.change_file(file_uri, real_content, restore_version)
        app.open_files[file_uri] = restore_version

    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    diagnostics = [
        {
            "severity": sev_map.get(d.get("severity", 0), 0),
            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
            "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
            "code": (d.get("code") or "") if isinstance(d.get("code"), str) else str(d.get("code", "")),
            "message": d.get("message", ""),
        }
        for d in raw_diags
    ]

    return JSONResponse({"diagnostics": diagnostics})


@mcp.custom_route("/lsp/workspace-diff", methods=["POST"])
async def lsp_workspace_diff(request: Request) -> JSONResponse:
    """Retorna diagnósticos de todo el workspace agrupados por archivo.

    Usa textDocument/diagnostic por cada archivo abierto (pull model)
    en vez de publishDiagnostics (push) para garantizar resultados frescos.
    """
    if app.ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    result: dict[str, list[dict]] = {}
    for uri in app.open_files:
        diags = await app.ty_server.diagnostic(uri)
        if app.ruff_server is not None:
            diags.extend(await app.ruff_server.diagnostic(uri))
        simplified = [
            {
                "severity": sev_map.get(d.get("severity", 0), 0),
                "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
                "code": (d.get("code") or "") if isinstance(d.get("code"), str) else str(d.get("code", "")),
                "message": d.get("message", ""),
            }
            for d in diags
        ]
        if simplified:
            result[uri] = simplified

    return JSONResponse({"diagnostics_by_file": result})
