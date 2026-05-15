"""Tools MCP basadas en ruff LSP (formatting, linting, code actions)."""

from pathlib import Path

from fastmcp import Context  # type: ignore[import-unresolved]

from ty_lsp.app import mcp
from ty_lsp.lsp import RuffServer
from ty_lsp.validation import FileError, ensure_file_open


@mcp.tool
async def format_file(file_path: str, ctx: Context) -> str:
    """Format a Python file using ruff and return the formatted source code.

    Args:
        file_path: Absolute path to the Python file.
        ctx: MCP context (auto-injected).

    Returns:
        The formatted source code, or an error message.
    """
    try:
        file_uri = await ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ruff: RuffServer = ctx.lifespan_context["ruff"]
    edits = await ruff.format_file(file_uri)

    if not edits:
        return "File is already formatted. No changes needed."

    # Apply text edits to the original content
    content = Path(file_path).read_text(encoding="utf-8")
    formatted = _apply_text_edits(content, edits)

    if formatted == content:
        return "File is already formatted. No changes needed."

    # Write the formatted content back
    Path(file_path).write_text(formatted, encoding="utf-8")

    # Count lines changed for summary
    orig_lines = content.splitlines()
    fmt_lines = formatted.splitlines()
    changed = sum(1 for a, b in zip(orig_lines, fmt_lines) if a != b)
    changed += abs(len(fmt_lines) - len(orig_lines))

    return f"File formatted successfully ({changed} line(s) changed).\n\nFormatted code:\n{formatted}"


@mcp.tool
async def lint_file(file_path: str, ctx: Context) -> str:
    """Lint a Python file using ruff and return diagnostics.

    Ruff provides fast linting with rules for unused imports, undefined
    variables, style issues, and many more.

    Args:
        file_path: Absolute path to the Python file.
        ctx: MCP context (auto-injected).

    Returns:
        List of lint diagnostics, or a message if clean.
    """
    try:
        file_uri = await ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ruff: RuffServer = ctx.lifespan_context["ruff"]
    diagnostics = await ruff.diagnostic(file_uri)

    if not diagnostics:
        return "No lint issues found."

    lines: list[str] = []
    sev_map = {1: "Error", 2: "Warning", 3: "Information", 4: "Hint"}
    for diag in diagnostics:
        severity = diag.get("severity", "?")
        sev_label = sev_map.get(severity, str(severity))

        range_ = diag.get("range", {})
        start = range_.get("start", {})
        line_num = start.get("line", "?") + 1
        col_num = start.get("character", "?") + 1

        message = diag.get("message", "Unknown error")
        code = diag.get("code", "")
        code_str = f" ({code})" if code else ""
        lines.append(
            f"  [{sev_label}] line {line_num}, col {col_num}: {message}{code_str}"
        )

    return "\n".join(lines)


@mcp.tool
async def apply_code_action(
    file_path: str, line: int, col: int, ctx: Context
) -> str:
    """Get available code actions (quick fixes) for a position in a Python file.

    Ruff provides actions like: fix unused imports, organize imports,
    auto-fix lint violations, etc.

    Args:
        file_path: Absolute path to the Python file.
        line: Line number (1-indexed).
        col: Column number (0-indexed).
        ctx: MCP context (auto-injected).

    Returns:
        Available code actions with their descriptions and edits.
    """
    try:
        file_uri = await ensure_file_open(ctx, file_path)
    except FileError as e:
        return str(e)

    ruff: RuffServer = ctx.lifespan_context["ruff"]
    line0 = line - 1

    actions = await ruff.code_actions(
        file_uri, line0, col, line0, col
    )

    if not actions:
        return "No code actions available at this position."

    lines: list[str] = []
    for action in actions:
        title = action.get("title", "Unknown action")
        kind = action.get("kind", "")
        kind_str = f" [{kind}]" if kind else ""
        is_preferred = " (preferred)" if action.get("isPreferred") else ""

        lines.append(f"- {title}{kind_str}{is_preferred}")

        # If the action has direct edits, show them
        edit = action.get("edit")
        if edit:
            changes = edit.get("changes", {})
            for text_edits in changes.values():
                for te in text_edits:
                    r = te.get("range", {})
                    s = r.get("start", {})
                    e = r.get("end", {})
                    new_text = te.get("newText", "")
                    s_line = s.get("line", 0) + 1
                    e_line = e.get("line", 0) + 1
                    if new_text.strip():
                        lines.append(
                            f"  Replace line(s) {s_line}-{e_line} with:\n  {new_text.rstrip()}"
                        )
                    else:
                        lines.append(
                            f"  Remove line(s) {s_line}-{e_line}"
                        )

        # If it has a command (some ruff actions use commands)
        command = action.get("command")
        if command:
            cmd_title = command.get("title", "")
            cmd_name = command.get("command", "")
            lines.append(f"  Command: {cmd_title} ({cmd_name})")

    return "\n".join(lines)


def _apply_text_edits(content: str, edits: list[dict]) -> str:
    """Apply LSP TextEdit list to content string.

    Edits are applied from bottom to top to preserve offsets.
    """
    lines = content.splitlines(keepends=True)
    # If content doesn't end with newline, ensure the last line is included
    if content and not content.endswith("\n"):
        if lines:
            lines[-1] = lines[-1] + "\n"

    # Sort edits by position (reverse order: bottom-up)
    sorted_edits = sorted(
        edits,
        key=lambda e: (
            e.get("range", {}).get("start", {}).get("line", 0),
            e.get("range", {}).get("start", {}).get("character", 0),
        ),
        reverse=True,
    )

    for edit in sorted_edits:
        r = edit.get("range", {})
        start = r.get("start", {})
        end = r.get("end", {})
        new_text = edit.get("newText", "")

        start_line = start.get("line", 0)
        start_char = start.get("character", 0)
        end_line = end.get("line", 0)
        end_char = end.get("character", 0)

        # Build the new content by splicing
        before = "".join(lines[:start_line])
        if start_line < len(lines):
            before += lines[start_line][:start_char]

        after = ""
        if end_line < len(lines):
            after = lines[end_line][end_char:]
        after += "".join(lines[end_line + 1 :])

        lines = (before + new_text + after).splitlines(keepends=True)

    result = "".join(lines)
    # Remove trailing newline we may have added
    if content and not content.endswith("\n") and result.endswith("\n"):
        result = result[:-1]
    return result
