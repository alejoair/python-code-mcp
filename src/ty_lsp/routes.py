"""Rutas HTTP personalizadas para los hooks de Claude Code."""

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from ty_lsp.app import mcp, open_files, ts_index, ty_server
from ty_lsp.ast_extract import extract_symbols


@mcp.custom_route("/lsp/open", methods=["POST"])
async def lsp_open(request: Request) -> JSONResponse:
    """Abre un archivo .py en ty (warm-up para hooks PreToolUse)."""
    if ty_server is None:
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
    if file_uri not in open_files:
        content = path.read_text(encoding="utf-8")
        await ty_server.open_file(file_uri, content)
        open_files[file_uri] = 1

    return JSONResponse({"ok": True})


@mcp.custom_route("/lsp/file-info", methods=["POST"])
async def lsp_file_info(request: Request) -> JSONResponse:
    """Retorna diagnósticos de tipo y símbolos de un archivo .py."""
    if ty_server is None:
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

    if file_uri not in open_files:
        await ty_server.open_file(file_uri, content)
        open_files[file_uri] = 1

    raw_diags = await ty_server.diagnostic(file_uri)
    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    diagnostics = [
        {
            "severity": sev_map.get(d.get("severity", 0), 0),
            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
            "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
            "message": d.get("message", ""),
        }
        for d in raw_diags
    ]

    symbols = extract_symbols(content)

    return JSONResponse({"diagnostics": diagnostics, "symbols": symbols})


@mcp.custom_route("/lsp/reload", methods=["POST"])
async def lsp_reload(request: Request) -> JSONResponse:
    """Recarga un .py en ty post-edición (didChange + didOpen fallback)."""
    if ty_server is None:
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

    if file_uri in open_files:
        version = open_files[file_uri] + 1
        await ty_server.change_file(file_uri, content, version)
        open_files[file_uri] = version
    else:
        await ty_server.open_file(file_uri, content)
        open_files[file_uri] = 1

    if ts_index is not None:
        ts_index.reindex_file(str(path))

    return JSONResponse({"ok": True})


@mcp.custom_route("/lsp/workspace-diff", methods=["POST"])
async def lsp_workspace_diff(request: Request) -> JSONResponse:
    """Retorna diagnósticos de todo el workspace agrupados por archivo.

    Usa textDocument/diagnostic por cada archivo abierto (pull model)
    en vez de publishDiagnostics (push) para garantizar resultados frescos.
    """
    if ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    result: dict[str, list[dict]] = {}
    for uri in open_files:
        diags = await ty_server.diagnostic(uri)
        simplified = [
            {
                "severity": sev_map.get(d.get("severity", 0), 0),
                "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                "col": d.get("range", {}).get("start", {}).get("character", 0) + 1,
                "message": d.get("message", ""),
            }
            for d in diags
        ]
        if simplified:
            result[uri] = simplified

    return JSONResponse({"diagnostics_by_file": result})
