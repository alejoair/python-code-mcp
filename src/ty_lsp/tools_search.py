"""Tool MCP search_code — búsqueda con contexto sintáctico via grep-ast."""

import re
from pathlib import Path

from grep_ast.grep_ast import TreeContext as _TreeContext  # type: ignore[import-unresolved]

from ty_lsp.app import mcp
from ty_lsp.gitignore import is_ignored, parse_gitignore
from ty_lsp.treesitter import _get_parser
from ty_lsp.validation import FileError, validate_py_file


class PyTreeContext(_TreeContext):
    """TreeContext subclass that uses our tree-sitter Parser instead of grep-ast's.

    grep-ast's TreeContext calls ``get_parser(lang)`` from tree-sitter-language-pack,
    which returns a native ``builtins.Parser`` without a ``.parse()`` method in
    tree-sitter-language-pack >= 1.8.  We override the init to use the project's own
    ``tree_sitter.Parser`` (which wraps the ``tree_sitter_python`` grammar).
    """

    def __init__(self, code: str):
        # Set scalar config before any method calls.
        self.color = False
        self.verbose = False
        self.line_number = True
        self.last_line = True
        self.margin = 3
        self.mark_lois = True
        self.header_max = 10
        self.loi_pad = 1
        self.show_top_of_file_parent_scope = True
        self.parent_context = True
        self.child_context = False

        self.filename = ""

        # Parse with our own parser.
        parser = _get_parser()
        tree = parser.parse(bytes(code, "utf-8"))

        self.lines = code.splitlines()
        self.num_lines = len(self.lines) + 1
        self.output_lines: dict[int, str] = {}
        self.scopes: list[set[int]] = [set() for _ in range(self.num_lines)]
        self.header: list[list[tuple[int, ...]]] = [
            list() for _ in range(self.num_lines)
        ]
        self.nodes: list[list[object]] = [list() for _ in range(self.num_lines)]

        self.walk_tree(tree.root_node)

        for i in range(self.num_lines):
            header = sorted(self.header[i])
            if len(header) > 1:
                size, head_start, head_end = header[0]
                if size > self.header_max:
                    head_end = head_start + self.header_max
            else:
                head_start = i
                head_end = i + 1
            self.header[i] = head_start, head_end

        self.show_lines: set[int] = set()
        self.lines_of_interest: set[int] = set()


@mcp.tool
async def search_code(
    pattern: str,
    file_path: str | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    max_results: int = 50,
    ctx: object | None = None,
) -> str:
    """Search for a pattern in Python files and return matches with syntactic context.

Searches for a text pattern (literal or regex) across Python files in the workspace
and returns matching lines enriched with their enclosing syntactic context (function,
class, etc.) using tree-sitter-based analysis.

Use this to find where a symbol, string, or pattern is used across the codebase with
enough surrounding context to understand each match without opening every file.

Args:
    pattern: Text literal to search (or regex if regex=True).
    file_path: If provided, restrict search to that single file. If None, searches all .py files in the workspace respecting .gitignore.
    regex: If True, interpret pattern as Python regex. If False, literal search.
    ignore_case: If True, case-insensitive search.
    max_results: Max number of files with matches to include in output. Default 50.

Returns:
    String with matches grouped by file, showing matched lines with syntactic context
    (enclosing function, class). If no matches, returns "No matches found.".
"""
    flags = re.IGNORECASE if ignore_case else 0
    if regex:
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex pattern: {e}"
    else:
        compiled = re.compile(re.escape(pattern), flags)

    root = Path.cwd()
    patterns = parse_gitignore(root)

    if file_path is not None:
        try:
            resolved = validate_py_file(file_path)
        except FileError as e:
            return str(e)
        files = [resolved]
    else:
        files = sorted(
            p
            for p in root.rglob("*.py")
            if not is_ignored(p.relative_to(root).as_posix(), patterns)
        )

    output_parts: list[str] = []
    total_matches = 0
    files_with_matches = 0

    for path in files:
        if files_with_matches >= max_results:
            break

        try:
            code = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        lines = code.splitlines()
        matched_lines: set[int] = set()
        for i, line in enumerate(lines):
            if compiled.search(line):
                matched_lines.add(i)
                total_matches += 1

        if not matched_lines:
            continue

        files_with_matches += 1
        rel_path = path.relative_to(root).as_posix()

        tc = PyTreeContext(code)
        tc.add_lines_of_interest(matched_lines)
        tc.add_context()
        rendered = tc.format()

        output_parts.append(f"=== {rel_path} ===\n{rendered}")

    if not output_parts:
        return "No matches found."

    output_parts.append(
        f"Found {total_matches} matches across {files_with_matches} files"
        + (
            f" (showing first {max_results} files)."
            if files_with_matches >= max_results
            else "."
        )
    )
    return "\n\n".join(output_parts)
