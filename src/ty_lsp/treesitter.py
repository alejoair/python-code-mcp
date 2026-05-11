"""Tree-sitter based structural analysis for Python files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tree_sitter as ts
import tree_sitter_python as tsp
from tree_sitter_language_pack._native import ProcessConfig, process

_PY_LANG = ts.Language(tsp.language())
_parser: ts.Parser | None = None


def _get_parser() -> ts.Parser:
    global _parser
    if _parser is None:
        _parser = ts.Parser(_PY_LANG)
    return _parser


def _node_text(node: ts.Node) -> str:
    assert node.text is not None
    return node.text.decode()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolLocation:
    file_path: str
    name: str
    kind: str  # "class", "function", "async_function"
    line: int  # 1-indexed
    end_line: int
    parent: str | None  # enclosing class name for methods


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _walk_symbols(node: ts.Node, parent: str | None = None) -> list[SymbolLocation]:
    results: list[SymbolLocation] = []

    for child in node.children:
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is not None:
                results.extend(_walk_symbols(inner, parent))
            continue

        if child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            name = _node_text(name_node) if name_node else "<unknown>"
            loc = SymbolLocation(
                file_path="",
                name=name,
                kind="class",
                line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                parent=parent,
            )
            results.append(loc)
            block = child.child_by_field_name("body")
            if block:
                results.extend(_walk_symbols(block, parent=name))

        elif child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            name = _node_text(name_node) if name_node else "<unknown>"
            is_async = any(c.type == "async" for c in child.children)
            loc = SymbolLocation(
                file_path="",
                name=name,
                kind="async_function" if is_async else "function",
                line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                parent=parent,
            )
            results.append(loc)

    return results


def _parse_file(file_path: str) -> tuple[ts.Tree, bytes]:
    parser = _get_parser()
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    return tree, source


def _find_class_node(root: ts.Node, class_name: str) -> ts.Node | None:
    for child in root.children:
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is not None and inner.type == "class_definition":
                name_node = inner.child_by_field_name("name")
                if name_node and _node_text(name_node) == class_name:
                    return child
        if child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            if name_node and _node_text(name_node) == class_name:
                return child
    return None


def _find_function_node(root: ts.Node, function_name: str, class_name: str | None = None) -> ts.Node | None:
    search_root = root
    if class_name is not None:
        class_node = None
        for child in root.children:
            target = child
            if child.type == "decorated_definition":
                target = child.child_by_field_name("definition") or child
            if target.type == "class_definition":
                n = target.child_by_field_name("name")
                if n and _node_text(n) == class_name:
                    class_node = child if child.type == "decorated_definition" else target
                    break
        if class_node is None:
            return None
        block = class_node.child_by_field_name("body")
        if block is None:
            return None
        search_root = block

    for child in search_root.children:
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is not None and inner.type == "function_definition":
                n = inner.child_by_field_name("name")
                if n and _node_text(n) == function_name:
                    return child
        if child.type == "function_definition":
            n = child.child_by_field_name("name")
            if n and _node_text(n) == function_name:
                return child
    return None


def _find_enclosing_node(root: ts.Node, line_0: int) -> ts.Node | None:
    best: ts.Node | None = None
    best_size = -1

    def visit(node: ts.Node) -> None:
        nonlocal best, best_size
        if node.type in ("function_definition", "class_definition", "decorated_definition"):
            if node.start_point[0] <= line_0 <= node.end_point[0]:
                size = node.end_point[0] - node.start_point[0]
                if size < best_size or best_size == -1:
                    best = node
                    best_size = size
        for child in node.children:
            visit(child)

    visit(root)
    return best


def _extract_docstring(block_node: ts.Node | None) -> str | None:
    if block_node is None:
        return None
    first = block_node.children[0] if block_node.children else None
    if first is None or first.type != "expression_statement":
        return None
    for expr in first.children:
        if expr.type == "string":
            return _node_text(expr)
    return None


def _get_signature(func_node: ts.Node) -> str:
    first = func_node.children[0] if func_node.children else None
    if first is None:
        return ""
    end_byte = func_node.end_byte
    for child in func_node.children:
        if child.type == "block":
            end_byte = child.start_byte
            break
    assert func_node.text is not None
    return func_node.text[:end_byte - func_node.start_byte].decode().strip()


# ---------------------------------------------------------------------------
# TreeSitterIndex — project-wide symbol index
# ---------------------------------------------------------------------------

class TreeSitterIndex:
    def __init__(self) -> None:
        self._symbols: dict[str, list[SymbolLocation]] = {}
        self._tree_cache: dict[str, ts.Tree] = {}

    def build(self, root: Path, gitignore_patterns: list[tuple[str, bool]] | None = None) -> None:
        if gitignore_patterns is None:
            gitignore_patterns = []
        for py_file in sorted(root.rglob("*.py")):
            rel = py_file.relative_to(root)
            if gitignore_patterns and self._is_ignored(rel, gitignore_patterns):
                continue
            self._index_file(str(py_file))

    def reindex_file(self, file_path: str) -> None:
        self._remove_file(file_path)
        self._index_file(file_path)

    def lookup(self, name: str) -> list[SymbolLocation]:
        return self._symbols.get(name, [])

    def get_tree(self, file_path: str) -> ts.Tree | None:
        return self._tree_cache.get(file_path)

    def _index_file(self, file_path: str) -> None:
        try:
            tree, _source = _parse_file(file_path)
        except OSError:
            return
        self._tree_cache[file_path] = tree
        symbols = _walk_symbols(tree.root_node)
        for sym in symbols:
            sym.file_path = file_path
            self._symbols.setdefault(sym.name, []).append(sym)

    def _remove_file(self, file_path: str) -> None:
        self._tree_cache.pop(file_path, None)
        for name in list(self._symbols.keys()):
            self._symbols[name] = [
                s for s in self._symbols[name] if s.file_path != file_path
            ]
            if not self._symbols[name]:
                del self._symbols[name]

    @staticmethod
    def _is_ignored(rel_path: Path, patterns: list[tuple[str, bool]]) -> bool:
        parts = rel_path.parts
        for pattern, is_negation in patterns:
            if pattern.endswith("/"):
                dirname = pattern.rstrip("/")
                if dirname in parts:
                    return not is_negation
            elif "/" in pattern:
                if str(rel_path).startswith(pattern.rstrip("/")):
                    return not is_negation
            else:
                if pattern in (part.rstrip("/") for part in parts):
                    return not is_negation
        return False


# ---------------------------------------------------------------------------
# Public extraction functions (called by MCP tools)
# ---------------------------------------------------------------------------

def find_identifier_at(file_path: str, line: int, character: int) -> tuple[int, int, int] | None:
    """Find the identifier token at or nearest to the given position.

    Returns (line, start_col, end_col) of the identifier, or None.
    Expands search left and right from the position if no identifier is at the exact spot.
    """
    try:
        tree, _source = _parse_file(file_path)
    except OSError:
        return None

    root = tree.root_node

    def _try_node(row: int, col: int) -> tuple[int, int, int] | None:
        node = root.descendant_for_point_range((row, col), (row, col))
        if node is None:
            return None
        # Already an identifier
        if node.type == "identifier":
            return (node.start_point[0], node.start_point[1], node.end_point[1])
        # Attribute access — use the attr part
        if node.type == "attribute":
            attr_node = node.child_by_field_name("attribute")
            if attr_node and attr_node.type == "identifier":
                return (attr_node.start_point[0], attr_node.start_point[1], attr_node.end_point[1])
        return None

    # Try exact position first
    result = _try_node(line, character)
    if result:
        return result

    # Search outward from the position, up to 30 cols each way
    line_end = root.end_point[1] if root.end_point[0] == line else 200
    for offset in range(1, 31):
        # Try right first
        if character + offset < line_end:
            result = _try_node(line, character + offset)
            if result:
                return result
        # Then left
        if character - offset >= 0:
            result = _try_node(line, character - offset)
            if result:
                return result

    return None


def list_file_symbols(file_path: str, kind_filter: str | None = None) -> str:
    source = Path(file_path).read_text(encoding="utf-8")
    config = ProcessConfig(language="python", structure=True)
    result = process(source, config)

    lines: list[str] = [f"Symbols in {Path(file_path).name}:"]
    for item in result.structure:
        kind_str = str(item.kind).lower()
        if kind_filter and kind_str != kind_filter:
            continue
        line = item.span.start_line
        marker = "class" if kind_str == "class" else "def"
        lines.append(f"{marker} {item.name:<40s} L{line}")

        for child in item.children:
            child_kind = str(child.kind).lower()
            if kind_filter and child_kind != kind_filter:
                continue
            child_line = child.span.start_line
            lines.append(f"    def {child.name:<38s} L{child_line}")

    if len(lines) == 1:
        return f"No symbols found in {file_path}"
    return "\n".join(lines)


def extract_function_body(file_path: str, function_name: str, class_name: str | None = None) -> str | None:
    try:
        tree, _source = _parse_file(file_path)
    except OSError:
        return None

    node = _find_function_node(tree.root_node, function_name, class_name)
    if node is None:
        return None
    return _node_text(node)


def extract_class_skeleton(file_path: str, class_name: str) -> str | None:
    try:
        tree, _source = _parse_file(file_path)
    except OSError:
        return None

    node = _find_class_node(tree.root_node, class_name)
    if node is None:
        return None

    class_def = node
    if node.type == "decorated_definition":
        decorators: list[str] = []
        for c in node.children:
            if c.type == "decorator":
                decorators.append(_node_text(c))
        class_def = node.child_by_field_name("definition")
        if class_def is None:
            return None
    else:
        decorators = []

    name_node = class_def.child_by_field_name("name")
    supers = class_def.child_by_field_name("superclasses")
    block = class_def.child_by_field_name("body")

    lines: list[str] = []
    for d in decorators:
        lines.append(d)

    header = f"class {_node_text(name_node)}" if name_node else "class <unknown>"
    if supers:
        header += f"({_node_text(supers)})"
    header += ":"
    lines.append(header)

    if block:
        doc = _extract_docstring(block)
        if doc:
            lines.append(f"    {doc}")

        for child in block.children:
            target = child
            if child.type == "decorated_definition":
                for c in child.children:
                    if c.type == "decorator":
                        lines.append(f"    {_node_text(c)}")
                target = child.child_by_field_name("definition")
                if target is None:
                    continue

            if target.type == "function_definition":
                sig = _get_signature(target)
                lines.append(f"    {sig}")

                fn_body = target.child_by_field_name("body")
                fn_doc = _extract_docstring(fn_body)
                if fn_doc:
                    lines.append(f"        {fn_doc}")

    return "\n".join(lines)


def extract_enclosing(file_path: str, line: int) -> str | None:
    try:
        tree, _source = _parse_file(file_path)
    except OSError:
        return None

    node = _find_enclosing_node(tree.root_node, line)
    if node is None:
        return None

    display_node = node
    if node.type == "decorated_definition":
        inner = node.child_by_field_name("definition")
        if inner:
            display_node = inner

    if display_node.type == "function_definition":
        n = display_node.child_by_field_name("name")
        name = _node_text(n) if n else "<anonymous>"
        kind_label = "async def" if any(c.type == "async" for c in display_node.children) else "def"
        parent_info = ""
        p = display_node.parent
        if p and p.type == "block":
            pp = p.parent
            if pp and pp.type == "class_definition":
                cn = pp.child_by_field_name("name")
                if cn:
                    parent_info = f" in {_node_text(cn)}"
    elif display_node.type == "class_definition":
        n = display_node.child_by_field_name("name")
        name = _node_text(n) if n else "<anonymous>"
        kind_label = "class"
        parent_info = ""
    else:
        name = display_node.type
        kind_label = "block"
        parent_info = ""

    start = node.start_point[0] + 1
    end = node.end_point[0] + 1
    header = f"Enclosing: {kind_label} {name}{parent_info} (lines {start}-{end})"
    code = _node_text(node)
    return f"{header}\n\n{code}"
