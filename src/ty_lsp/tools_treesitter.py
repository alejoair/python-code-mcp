"""Tools MCP estructurales basadas en tree-sitter."""

from ty_lsp.app import mcp
from ty_lsp.treesitter import (
    TreeSitterIndex,
    extract_class_skeleton,
    extract_enclosing,
    extract_function_body,
    list_file_symbols,
)
from ty_lsp.validation import FileError, validate_py_file


@mcp.tool
async def list_symbols(
    file_path: str,
    kind: str | None = None,
    ctx: object | None = None,
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
        validate_py_file(file_path)
    except FileError as e:
        return str(e)

    return list_file_symbols(file_path, kind_filter=kind)


@mcp.tool
async def get_function_body(
    file_path: str,
    function_name: str,
    class_name: str | None = None,
    ctx: object | None = None,
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
        validate_py_file(file_path)
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
    ctx: object | None = None,
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
        validate_py_file(file_path)
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
    ctx: object | None = None,
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
        validate_py_file(file_path)
    except FileError as e:
        return str(e)

    result = extract_enclosing(file_path, line - 1)
    if result is None:
        return f"No enclosing unit found at line {line} in {file_path}"
    return result
