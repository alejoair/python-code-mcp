"""Tools MCP semánticas basadas en ty LSP."""

from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import Context  # type: ignore[import-unresolved]

from ty_lsp.app import mcp
from ty_lsp.lsp import RuffServer, TyServer
from ty_lsp.lsp_helpers import format_location, uri_to_path
from ty_lsp.treesitter import find_identifier_at
from ty_lsp.validation import FileError, ensure_file_open


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
        file_uri = await ensure_file_open(ctx, file_path)
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
        file_uri = await ensure_file_open(ctx, file_path)
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
        path = uri_to_path(uri)
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
        file_uri = await ensure_file_open(ctx, file_path)
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

    result_lines = [format_location(loc) for loc in locations]
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
        file_uri = await ensure_file_open(ctx, file_path)
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

    result_lines = [format_location(loc) for loc in locations]
    return "\n".join(result_lines)


@mcp.tool
async def restart_servers(ctx: Context) -> str:
    """Restart the ty and ruff LSP servers to pick up configuration changes.

    Use this after editing pyproject.toml to apply new ty rules or ruff
    lint settings without restarting the entire MCP server.

    Stops both LSP subprocesses, restarts them, re-opens all project files,
    and prints the updated configuration from pyproject.toml.
    """
    from ty_lsp.app import _print_configured_rules
    from ty_lsp.treesitter import TreeSitterIndex
    from ty_lsp.validation import open_project_files, parse_gitignore

    import ty_lsp.app as app

    old_ty: TyServer = ctx.lifespan_context["ty"]
    old_ruff: RuffServer = ctx.lifespan_context["ruff"]

    # Stop old servers
    print("[python-code-mcp] Deteniendo servidores...", file=sys.stderr)
    await old_ruff.stop()
    await old_ty.stop()

    # Start fresh servers
    root_path = Path.cwd()
    root_uri = root_path.as_uri()
    patterns = parse_gitignore(root_path)

    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    open_files = await open_project_files(ty, root_path, patterns)

    ruff = RuffServer()
    await ruff.start()
    await ruff.initialize(root_uri)

    for uri in open_files:
        file_path_str = uri_to_path(uri)
        try:
            content = Path(file_path_str).read_text(encoding="utf-8")
            await ruff.open_file(uri, content)
        except OSError:
            pass

    ts_index = TreeSitterIndex()
    ts_index.build(root_path, patterns)

    # Update global state
    app.ty_server = ty
    app.ruff_server = ruff
    app.open_files = open_files
    app.ts_index = ts_index

    # Update lifespan context (so subsequent tool calls use the new servers)
    ctx.lifespan_context["ty"] = ty
    ctx.lifespan_context["ruff"] = ruff
    ctx.lifespan_context["open_files"] = open_files
    ctx.lifespan_context["ts_index"] = ts_index

    # Print updated config
    _print_configured_rules(root_path)

    return (
        f"Servidores reiniciados correctamente.\n"
        f"  ty: {len(open_files)} archivo(s) abiertos\n"
        f"  ruff: {len(open_files)} archivo(s) abiertos\n"
        f"  tree-sitter: índice reconstruido\n"
        f"  Configuración recargada desde pyproject.toml"
    )


@mcp.tool()
def set_block_mode(
    block_mode: str | None = None,
    block_severity: int | None = None,
    reason: str = "",
) -> str:
    """Modify the hook block mode at runtime without editing pyproject.toml.

    Allows temporarily adjusting block severity for scenarios like large
    refactors or projects with pre-existing errors. Always set the highest
    severity that allows your work to proceed. Reset to defaults when done.

    Args:
        block_mode: Block mode override. One of:
            "off" - No blocking (use only when necessary)
            "ty" - Block only on type checker errors
            "ruff" - Block only on linter errors
            "all" - Block on both type and lint errors
            None - Reset to pyproject.toml value
        block_severity: Minimum severity to block. One of:
            0 - Disabled (no blocking)
            1 - Error only
            2 - Error + Warning
            3 - Error + Warning + Info
            None - Reset to pyproject.toml value
        reason: Why you are changing the block mode (logged)

    Returns:
        Confirmation message with the effective configuration.
    """
    import ty_lsp.app as app

    if block_mode is None and block_severity is None:
        # Reset to defaults
        app.block_mode_override = None
        return "Block mode reset to pyproject.toml defaults."

    # Build or update override
    override = app.block_mode_override or {}
    if block_mode is not None:
        override["block_mode"] = block_mode
    if block_severity is not None:
        override["block_severity"] = block_severity
    app.block_mode_override = override

    # Log the change
    print(
        f"[python-code-mcp] Block mode changed: "
        f"mode={override.get('block_mode')}, "
        f"severity={override.get('block_severity')}, "
        f"reason={reason!r}",
        file=sys.stderr,
    )

    mode = override.get("block_mode", "(from config)")
    sev = override.get("block_severity", "(from config)")
    return (
        f"Block mode updated.\n"
        f"  block-mode: {mode}\n"
        f"  block-severity: {sev}\n"
        f"  reason: {reason or '(none)'}\n"
        f"\n"
        f"Call with no arguments to reset to pyproject.toml defaults."
    )
