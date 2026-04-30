"""
server.py — Servidor MCP que expone funcionalidades del type checker ty.

Usa FastMCP con transporte stdio. El servidor ty se maneja internamente
como subprocess via lifespan.
"""

import fnmatch
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP, Context  # type: ignore[import-unresolved]

from ty_lsp.lsp import TyServer


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


async def _open_project_files(ty: TyServer, root: Path) -> set[str]:
    """Abre todos los archivos .py del proyecto en ty via didOpen.

    Respeta .gitignore. Retorna el set de URIs abiertos.
    """
    patterns = _parse_gitignore(root)

    py_files: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if _is_ignored(rel, patterns):
            continue
        py_files.append(p)

    open_uris: set[str] = set()
    for p in py_files:
        file_uri = p.resolve().as_uri()
        content = p.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_uris.add(file_uri)

    if py_files:
        print(
            f"[ty] {len(py_files)} archivo(s) Python precargados",
            file=sys.stderr,
        )

    return open_uris


async def _ensure_file_open(ctx: Context, file_path: str) -> str:
    """Valida file_path y asegura que ty lo tenga abierto via didOpen.

    Retorna el file URI. Lanza FileError si el path es inválido.
    """
    ty: TyServer = ctx.lifespan_context["ty"]
    open_files: set[str] = ctx.lifespan_context["open_files"]

    path = Path(file_path).resolve()
    if not path.exists():
        raise FileError(f"Error: el archivo no existe: {file_path}")
    if not path.suffix == ".py":
        raise FileError(f"Error: el archivo no es Python: {file_path}")

    file_uri = path.as_uri()
    if file_uri not in open_files:
        content = path.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_files.add(file_uri)

    return file_uri


@asynccontextmanager
async def ty_lifespan(server: FastMCP):
    """Lifespan que inicia y detiene ty server como subprocess."""
    root_path = Path.cwd()
    root_uri = root_path.as_uri()

    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    open_files = await _open_project_files(ty, root_path)

    yield {"ty": ty, "open_files": open_files}

    await ty.stop()


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
        line: Línea del símbolo (0-indexed).
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

    # Solicitar hover
    result = await ty.hover(file_uri, line, character)
    if result is None:
        return "No hay información de hover disponible para esa posición."

    # Extraer el contenido del hover
    contents = result.get("contents")
    if contents is None:
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


def _format_location(loc: dict) -> str:
    """Formatea una Location LSP (uri + range) como texto legible."""
    from urllib.parse import urlparse, unquote

    uri = loc.get("uri", "")
    path = unquote(urlparse(uri).path)
    # En Windows, quitar el leading / del file URI
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]

    range_ = loc.get("range", {})
    start = range_.get("start", {})
    line_num = start.get("line", 0) + 1
    col_num = start.get("character", 0) + 1

    return f"{path}:{line_num}:{col_num}"


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
        line: Línea del símbolo (0-indexed).
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
    locations = await ty.definition(file_uri, line, col)

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
        line: Línea del símbolo (0-indexed).
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
    locations = await ty.references(file_uri, line, col)

    if not locations:
        return "No se encontraron referencias al símbolo."

    result_lines = [_format_location(loc) for loc in locations]
    return "\n".join(result_lines)


@mcp.tool
async def rename_symbol(
    file_path: str,
    line: int,
    col: int,
    new_name: str,
    ctx: Context,
) -> str:
    """Rename a class, function, or variable across the entire codebase safely using LSP.

    This will find ALL references and rename them atomically. Use this when
    you need to refactor names — it's safer than using Edit tool which might
    miss references in other files.

    Args:
        file_path: Path absoluto al archivo Python.
        line: Línea del símbolo (0-indexed).
        col: Columna del símbolo (0-indexed).
        new_name: Nuevo nombre para el símbolo.
        ctx: Contexto MCP (inyectado automáticamente).

    Returns:
        Resumen de los cambios realizados.
    """
    try:
        file_uri = await _ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ty: TyServer = ctx.lifespan_context["ty"]
    workspace_edit = await ty.rename(file_uri, line, col, new_name)

    if workspace_edit is None:
        return "No se pudo renombrar el símbolo (verifica que sea un nombre válido)."

    changes = workspace_edit.get("changes", {})
    if not changes:
        return "No se encontraron cambios para renombrar."

    total = sum(len(edits) for edits in changes.values())
    file_count = len(changes)

    # Aplicar los cambios
    from urllib.parse import urlparse, unquote

    for uri, edits in changes.items():
        path = unquote(urlparse(uri).path)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]

        p = Path(path)
        if not p.exists():
            continue

        content = p.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Aplicar edits en orden inverso para no desplazar offsets
        for edit in sorted(
            edits,
            key=lambda e: (
                e["range"]["start"]["line"],
                e["range"]["start"]["character"],
            ),
            reverse=True,
        ):
            sl = edit["range"]["start"]["line"]
            sc = edit["range"]["start"]["character"]
            el = edit["range"]["end"]["line"]
            ec = edit["range"]["end"]["character"]
            new_text = edit["newText"]

            # Construir el contenido reemplazado
            before = "\n".join(lines[:sl])
            if before and sl > 0:
                before += "\n"
            before += lines[sl][:sc] if sl < len(lines) else ""

            after = lines[el][ec:] if el < len(lines) else ""
            tail = "\n".join(lines[el + 1 :])
            if tail:
                after += "\n" + tail

            content = before + new_text + after
            lines = content.split("\n")

        p.write_text(content, encoding="utf-8")

    return f"Renombrado a '{new_name}': {total} cambio(s) en {file_count} archivo(s)."


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

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
