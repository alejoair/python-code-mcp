"""
server.py — Servidor MCP que expone funcionalidades del type checker ty.

Usa FastMCP con transporte stdio. El servidor ty se maneja internamente
como subprocess via lifespan.
"""

import ast
import fnmatch
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP, Context  # type: ignore[import-unresolved]
from starlette.requests import Request
from starlette.responses import JSONResponse

from ty_lsp.lsp import TyServer
from ty_lsp.treesitter import TreeSitterIndex, list_file_symbols, extract_function_body, extract_class_skeleton, extract_enclosing, find_identifier_at

# Estado global accesible por las rutas HTTP custom
_ty_server: TyServer | None = None
_open_files: dict[str, int] = {}
_ts_index: TreeSitterIndex | None = None


class FileError(Exception):
    """Raised when a file path fails validation for LSP operations."""


def _parse_gitignore(root: Path) -> list[tuple[str, bool]]:
    """Parsea .gitignore y retorna lista de (pattern, is_negation).

    Soporta patrones con /, wildcards (*, ?, []), negaciones (!),
    y trailing / para directorios. Patrones sin / se matchean
    contra cualquier segmento del path.
    """
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        return []

    patterns: list[tuple[str, bool]] = []
    for line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        negation = line.startswith("!")
        if negation:
            line = line[1:]
        patterns.append((line, negation))
    return patterns


def _is_ignored(rel_path: str, patterns: list[tuple[str, bool]]) -> bool:
    """Determina si un path relativo es ignorado por los patrones de gitignore.

    Usa la misma lógica que git: último match gana, negaciones des-ignoran.
    """
    result = False
    for pattern, negation in patterns:
        # Patrones de directorio (terminan en /)
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            # Matchea si el path está dentro de ese directorio
            # ej: ".venv/" matchea ".venv/lib/site-packages/x.py"
            if rel_path.startswith(dir_name + "/") or rel_path == dir_name:
                result = not negation
        # Patrones con / se matchean contra el path completo
        elif "/" in pattern:
            if fnmatch.fnmatch(rel_path, pattern):
                result = not negation
        else:
            # Patrones sin / se matchean contra cualquier segmento
            name = Path(rel_path).name
            if fnmatch.fnmatch(name, pattern):
                result = not negation
    return result


async def _open_project_files(ty: TyServer, root: Path, patterns: list[tuple[str, bool]] | None = None) -> dict[str, int]:
    """Abre todos los archivos .py del proyecto en ty via didOpen.

    Respeta .gitignore. Retorna dict de URI → versión.
    """
    if patterns is None:
        patterns = _parse_gitignore(root)

    py_files: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if _is_ignored(rel, patterns):
            continue
        py_files.append(p)

    open_uris: dict[str, int] = {}
    for p in py_files:
        file_uri = p.resolve().as_uri()
        content = p.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_uris[file_uri] = 1

    if py_files:
        print(
            f"[ty] {len(py_files)} archivo(s) Python precargados",
            file=sys.stderr,
        )

    return open_uris


def _validate_py_file(file_path: str) -> Path:
    """Valida que file_path exista y sea .py. Lanza FileError si no."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileError(f"Error: el archivo no existe: {file_path}")
    if not path.suffix == ".py":
        raise FileError(f"Error: el archivo no es Python: {file_path}")
    return path


async def _ensure_file_open(ctx: Context, file_path: str) -> str:
    """Valida file_path y asegura que ty lo tenga abierto via didOpen.

    Retorna el file URI. Lanza FileError si el path es inválido.
    """
    ty: TyServer = ctx.lifespan_context["ty"]
    open_files: dict[str, int] = ctx.lifespan_context["open_files"]

    path = _validate_py_file(file_path)

    file_uri = path.as_uri()
    if file_uri not in open_files:
        content = path.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_files[file_uri] = 1

    return file_uri


@asynccontextmanager
async def ty_lifespan(server: FastMCP):
    """Lifespan que inicia y detiene ty server como subprocess."""
    global _ty_server, _open_files, _ts_index

    root_path = Path.cwd()
    root_uri = root_path.as_uri()

    patterns = _parse_gitignore(root_path)

    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    open_files = await _open_project_files(ty, root_path, patterns)

    ts_index = TreeSitterIndex()
    ts_index.build(root_path, patterns)

    _ty_server = ty
    _open_files = open_files
    _ts_index = ts_index

    yield {"ty": ty, "open_files": open_files, "ts_index": ts_index}

    await ty.stop()
    _ty_server = None
    _open_files = {}
    _ts_index = None


mcp = FastMCP(
    name="python-code-mcp",
    instructions=(
        "Servidor MCP que expone funcionalidades del type checker ty "
        "via Language Server Protocol. Ty proporciona inferencia de tipos, "
        "diagnósticos y más para archivos Python."
    ),
    lifespan=ty_lifespan,
)


@mcp.tool
async def hover(
    file_path: str,
    line: int,
    character: int,
    ctx: Context,
) -> str:
    """Obtiene información de tipo (hover) para un símbolo en un archivo Python.

    Args:
        file_path: Path absoluto al archivo Python.
        line: Línea del símbolo (1-indexed).
        character: Columna del símbolo (0-indexed).
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Información de tipo inferido por ty, o un mensaje si no hay info.
    """
    try:
        file_uri = await _ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ty: TyServer = ctx.lifespan_context["ty"]

    # Convertir a 0-indexed para ty y tree-sitter
    line0 = line - 1

    # Solicitar hover
    result = await ty.hover(file_uri, line0, character)
    contents = result.get("contents") if result else None

    # Si no hay info, usar tree-sitter para encontrar el identificador y reintentar
    if not contents:
        ident = find_identifier_at(file_path, line0, character)
        if ident is not None and (ident[1] != character or ident[0] != line0):
            result = await ty.hover(file_uri, ident[0], ident[1])
            contents = result.get("contents") if result else None

    if not contents:
        return "No hay información de hover disponible para esa posición."

    if isinstance(contents, dict):
        value = contents.get("value", "")
        if value:
            return value
        return "No hay información de hover disponible para esa posición."

    if isinstance(contents, str) and contents:
        return contents

    return "No hay información de hover disponible para esa posición."


@mcp.tool
async def type_check(file_path: str, ctx: Context) -> str:
    """Check a Python file for type errors using the ty type checker.

    Args:
        file_path: Path absoluto al archivo Python.
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Lista de diagnósticos de tipo, o un mensaje si no hay errores.
    """
    try:
        file_uri = await _ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ty: TyServer = ctx.lifespan_context["ty"]
    diagnostics = await ty.diagnostic(file_uri)

    if not diagnostics:
        return "No se encontraron errores de tipo."

    lines: list[str] = []
    for diag in diagnostics:
        severity = diag.get("severity", "?")
        sev_map = {1: "Error", 2: "Warning", 3: "Information", 4: "Hint"}
        sev_label = sev_map.get(severity, str(severity))

        range_ = diag.get("range", {})
        start = range_.get("start", {})
        line_num = start.get("line", "?") + 1
        col_num = start.get("character", "?") + 1

        message = diag.get("message", "Unknown error")
        lines.append(f"  [{sev_label}] line {line_num}, col {col_num}: {message}")

    return "\n".join(lines)


@mcp.tool
async def workspace_check(ctx: Context) -> str:
    """Run type checking across the entire workspace using ty's semantic engine.

    This analyzes all Python files in the project and reports diagnostics grouped
    by file. Unlike per-file type_check, this uses ty's inference engine over the
    full module graph — if you change a public signature in one file, importers in
    other files will show updated diagnostics in the same pass.

    Use this to answer "what broke with this change?" at the project level.
    """
    ty: TyServer = ctx.lifespan_context["ty"]
    all_diags = await ty.workspace_diagnostic()

    if not all_diags:
        return "No se encontraron errores de tipo en el workspace."

    lines: list[str] = []
    total_diags = 0
    sev_map = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}

    for uri, diags in all_diags.items():
        path = _uri_to_path(uri)
        lines.append(f"\n{path}:")
        for diag in diags:
            severity = diag.get("severity", "?")
            sev_label = sev_map.get(severity, str(severity))
            range_ = diag.get("range", {})
            start = range_.get("start", {})
            line_num = start.get("line", "?") + 1
            col_num = start.get("character", "?") + 1
            message = diag.get("message", "Unknown error")
            lines.append(f"  [{sev_label}] line {line_num}, col {col_num}: {message}")
            total_diags += 1

    if total_diags == 0:
        return "No se encontraron errores de tipo en el workspace."

    lines.insert(0, f"{total_diags} issue(s) en el workspace:")
    return "\n".join(lines)


def _format_location(loc: dict) -> str:
    """Formatea una Location LSP (uri + range) como texto legible."""
    from urllib.parse import urlparse, unquote

    uri = loc.get("uri", "")
    path = _uri_to_path(uri)

    range_ = loc.get("range", {})
    start = range_.get("start", {})
    line_num = start.get("line", 0) + 1
    col_num = start.get("character", 0) + 1

    return f"{path}:{line_num}:{col_num}"


def _uri_to_path(uri: str) -> str:
    """Convierte un file URI a path del filesystem."""
    from urllib.parse import urlparse, unquote

    path = unquote(urlparse(uri).path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


@mcp.tool
async def find_definition(
    file_path: str,
    line: int,
    col: int,
    ctx: Context,
) -> str:
    """Find where a symbol (class, function, variable) is defined using LSP.

    This jumps to the definition even if it's in another file. Use this when
    you need to understand how a function or class works — it will show you
    the actual implementation code.

    Args:
        file_path: Path absoluto al archivo Python.
        line: Línea del símbolo (1-indexed).
        col: Columna del símbolo (0-indexed).
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Ubicación de la definición del símbolo.
    """
    try:
        file_uri = await _ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ty: TyServer = ctx.lifespan_context["ty"]
    line0 = line - 1
    locations = await ty.definition(file_uri, line0, col)

    if not locations:
        ident = find_identifier_at(file_path, line0, col)
        if ident is not None and (ident[1] != col or ident[0] != line0):
            locations = await ty.definition(file_uri, ident[0], ident[1])

    if not locations:
        return "No se encontró la definición del símbolo."

    result_lines = [_format_location(loc) for loc in locations]
    return "\n".join(result_lines)


@mcp.tool
async def find_references(
    file_path: str,
    line: int,
    col: int,
    ctx: Context,
) -> str:
    """Find all references to a symbol across the codebase.

    Use this to see where a function, class, or variable is used before
    refactoring or deleting it.

    Args:
        file_path: Path absoluto al archivo Python.
        line: Línea del símbolo (1-indexed).
        col: Columna del símbolo (0-indexed).
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Lista de todas las ubicaciones donde se referencia el símbolo.
    """
    try:
        file_uri = await _ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ty: TyServer = ctx.lifespan_context["ty"]
    line0 = line - 1
    locations = await ty.references(file_uri, line0, col)

    if not locations:
        ident = find_identifier_at(file_path, line0, col)
        if ident is not None and (ident[1] != col or ident[0] != line0):
            locations = await ty.references(file_uri, ident[0], ident[1])

    if not locations:
        return "No se encontraron referencias al símbolo."

    result_lines = [_format_location(loc) for loc in locations]
    return "\n".join(result_lines)


@mcp.tool
async def list_symbols(
    file_path: str,
    kind: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Structural outline of a Python file. Shows classes, methods, and functions with line numbers.

    Use this to quickly understand the structure of a file without reading the entire contents.

    Args:
        file_path: Absolute path to the Python file.
        kind: Optional filter — "class", "function", or "method" to show only that kind.

    Returns:
        Human-readable structural outline with symbol names and line numbers.
    """
    try:
        _validate_py_file(file_path)
    except FileError as e:
        return str(e)

    return list_file_symbols(file_path, kind_filter=kind)


@mcp.tool
async def get_function_body(
    file_path: str,
    function_name: str,
    class_name: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Extract the exact source code of a function or method by name, including decorators and docstring.

    Use this instead of reading the entire file when you only need one specific function.
    Preserves original formatting, comments, and docstrings.

    Args:
        file_path: Absolute path to the Python file.
        function_name: Name of the function to extract.
        class_name: Optional class name if extracting a method.

    Returns:
        The full source code of the function, or an error message if not found.
    """
    try:
        _validate_py_file(file_path)
    except FileError as e:
        return str(e)

    result = extract_function_body(file_path, function_name, class_name)
    if result is None:
        loc = f"{class_name}.{function_name}" if class_name else function_name
        return f"Function '{loc}' not found in {file_path}"
    return result


@mcp.tool
async def get_class_skeleton(
    file_path: str,
    class_name: str,
    ctx: Context | None = None,
) -> str:
    """Extract class structure: base classes, method signatures, decorators, and docstrings. No method bodies.

    Use this to understand a class's interface without reading implementation details.

    Args:
        file_path: Absolute path to the Python file.
        class_name: Name of the class to extract.

    Returns:
        The class skeleton with method signatures but no implementation bodies.
    """
    try:
        _validate_py_file(file_path)
    except FileError as e:
        return str(e)

    result = extract_class_skeleton(file_path, class_name)
    if result is None:
        return f"Class '{class_name}' not found in {file_path}"
    return result


@mcp.tool
async def extract_enclosing_unit(
    file_path: str,
    line: int,
    ctx: Context | None = None,
) -> str:
    """Find the minimal enclosing unit (function, method, or class) for a given line number.

    Use this when ty reports an error at a line and you want to see only the surrounding context.
    Returns the complete source of the enclosing unit with a header indicating what was found.

    Args:
        file_path: Absolute path to the Python file.
        line: Line number (1-indexed).

    Returns:
        Source code of the enclosing unit with a location header.
    """
    try:
        _validate_py_file(file_path)
    except FileError as e:
        return str(e)

    result = extract_enclosing(file_path, line - 1)
    if result is None:
        return f"No enclosing unit found at line {line} in {file_path}"
    return result


# rename_symbol desactivada — el rename de ty no es confiable (rename textual, no semántico).
# Puede corromper archivos que no tienen relación con el símbolo renombrado.


def _extract_symbols(source: str) -> list[dict]:
    """Extrae clases y funciones de un archivo Python usando ast (2 niveles)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    symbols: list[dict] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno, "depth": 0})
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    symbols.append({"kind": kind, "name": child.name, "line": child.lineno, "depth": 1})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            symbols.append({"kind": kind, "name": node.name, "line": node.lineno, "depth": 0})
    return symbols


@mcp.custom_route("/lsp/open", methods=["POST"])
async def lsp_open(request: Request) -> JSONResponse:
    """Abre un archivo .py en ty (warm-up para hooks PreToolUse)."""
    if _ty_server is None:
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
    if file_uri not in _open_files:
        content = path.read_text(encoding="utf-8")
        await _ty_server.open_file(file_uri, content)
        _open_files[file_uri] = 1

    return JSONResponse({"ok": True})


@mcp.custom_route("/lsp/file-info", methods=["POST"])
async def lsp_file_info(request: Request) -> JSONResponse:
    """Retorna diagnósticos de tipo y símbolos de un archivo .py."""
    if _ty_server is None:
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

    if file_uri not in _open_files:
        await _ty_server.open_file(file_uri, content)
        _open_files[file_uri] = 1

    raw_diags = await _ty_server.diagnostic(file_uri)
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

    symbols = _extract_symbols(content)

    return JSONResponse({"diagnostics": diagnostics, "symbols": symbols})


@mcp.custom_route("/lsp/reload", methods=["POST"])
async def lsp_reload(request: Request) -> JSONResponse:
    """Recarga un .py en ty post-edición (didChange + didOpen fallback)."""
    if _ty_server is None:
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

    if file_uri in _open_files:
        version = _open_files[file_uri] + 1
        await _ty_server.change_file(file_uri, content, version)
        _open_files[file_uri] = version
    else:
        await _ty_server.open_file(file_uri, content)
        _open_files[file_uri] = 1

    if _ts_index is not None:
        _ts_index.reindex_file(str(path))

    return JSONResponse({"ok": True})


@mcp.custom_route("/lsp/workspace-diff", methods=["POST"])
async def lsp_workspace_diff(request: Request) -> JSONResponse:
    """Retorna diagnósticos de todo el workspace agrupados por archivo.

    Usa textDocument/diagnostic por cada archivo abierto (pull model)
    en vez de publishDiagnostics (push) para garantizar resultados frescos.
    """
    if _ty_server is None:
        return JSONResponse({"error": "servidor no inicializado"}, status_code=503)

    sev_map = {1: 1, 2: 2, 3: 3, 4: 4}
    result: dict[str, list[dict]] = {}
    for uri in _open_files:
        diags = await _ty_server.diagnostic(uri)
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


def main() -> None:
    """Entry point del servidor MCP.

    Sin argumentos: lanza el servidor MCP.
    Con 'install': registra el servidor en Claude Code y sale.
    """
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "install":
        from ty_lsp.install import run_install
        run_install()
        return

    mcp.run(transport="http")


if __name__ == "__main__":
    main()
