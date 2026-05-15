"""Tool MCP project_overview — snapshot completo del proyecto en una invocación."""

from __future__ import annotations

from pathlib import Path

from fastmcp import Context  # type: ignore[import-unresolved]

from ty_lsp.app import mcp
from ty_lsp.gitignore import is_ignored, parse_gitignore
from ty_lsp.lsp import RuffServer, TyServer
from ty_lsp.treesitter import _parse_file, _walk_symbols

_VALID_SECTIONS = (
    "metadata",
    "structure",
    "entry_points",
    "stack",
    "tool_config",
    "health",
    "public_api",
)

_KNOWN_FRAMEWORKS = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "fastmcp": "FastMCP",
    "mcp": "MCP SDK",
    "starlette": "Starlette",
    "pydantic": "Pydantic",
    "sqlalchemy": "SQLAlchemy",
    "celery": "Celery",
    "pytest": "pytest",
    "httpx": "HTTPX",
    "requests": "Requests",
    "click": "Click",
    "typer": "Typer",
    "rich": "Rich",
    "tree-sitter": "tree-sitter",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "scipy": "SciPy",
}


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _load_pyproject() -> dict | None:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redefine]

    toml_path = Path.cwd() / "pyproject.toml"
    if not toml_path.exists():
        return None
    with open(toml_path, "rb") as f:
        return tomllib.load(f)


def _walk_py_files() -> list[Path]:
    root = Path.cwd()
    patterns = parse_gitignore(root)
    files: list[Path] = []
    for py_file in sorted(root.rglob("*.py")):
        rel = str(py_file.relative_to(root))
        if patterns and is_ignored(rel, patterns):
            continue
        files.append(py_file)
    return files


def _count_lines(py_files: list[Path]) -> int:
    total = 0
    for f in py_files:
        try:
            total += sum(1 for _ in f.open(encoding="utf-8"))
        except OSError:
            pass
    return total


def _render_tree(py_files: list[Path]) -> str:
    if not py_files:
        return "(no Python files found)"

    root = Path.cwd()
    tree: dict = {}
    for f in py_files:
        parts = f.relative_to(root).parts
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    lines: list[str] = []

    def _render(node: dict, prefix: str = "") -> None:
        entries = sorted(node.keys())
        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}")
            extension = "    " if is_last else "│   "
            _render(node[name], prefix + extension)

    _render(tree)
    return "\n".join(lines)


def _find_main_package(config: dict) -> Path | None:
    """Find the main Python package via hatch config or heuristic."""
    root = Path.cwd()

    # Try [tool.hatch.build.targets.wheel].packages
    hatch_pkgs = (
        config.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages", [])
    )
    for pkg_rel in hatch_pkgs:
        pkg_path = root / pkg_rel
        if pkg_path.is_dir() and (pkg_path / "__init__.py").exists():
            return pkg_path

    # Heuristic: first directory under src/ or root with __init__.py
    for candidate in (root / "src").iterdir() if (root / "src").is_dir() else root.iterdir():
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            rel = candidate.relative_to(root)
            # Skip hidden/dunder dirs
            if not rel.name.startswith(("_", ".")):
                return candidate

    return None


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _section_metadata(config: dict | None, py_files: list[Path]) -> str:
    if config is None:
        return "## Metadata\n\n(no pyproject.toml)"

    project = config.get("project", {})
    lines: list[str] = ["## Metadata", ""]

    name = project.get("name", "(unknown)")
    version = project.get("version", "(unknown)")
    python_req = project.get("requires-python", "(unknown)")
    lines.append(f"Project: {name}")
    lines.append(f"Version: {version}")
    lines.append(f"Python: {python_req}")
    lines.append(f"Root: {Path.cwd()}")
    lines.append(f"Python files: {len(py_files)}")
    lines.append(f"Total lines: {_count_lines(py_files)}")

    return "\n".join(lines)


def _section_structure(py_files: list[Path]) -> str:
    return f"## Structure\n\n{_render_tree(py_files)}"


def _section_entry_points(config: dict | None) -> str:
    if config is None:
        return "## Entry Points\n\n(no pyproject.toml)"

    project = config.get("project", {})
    scripts = project.get("scripts", {})
    entry_points = project.get("entry-points", {})

    lines: list[str] = ["## Entry Points", ""]

    if scripts:
        for name, target in scripts.items():
            lines.append(f"  {name} -> {target}")
    else:
        lines.append("  (no console scripts)")

    for group, entries in entry_points.items():
        lines.append(f"\n  [{group}]")
        for name, target in entries.items():
            lines.append(f"    {name} -> {target}")

    return "\n".join(lines)


def _section_stack(config: dict | None) -> str:
    if config is None:
        return "## Stack\n\n(no pyproject.toml)"

    deps = config.get("project", {}).get("dependencies", [])
    lines: list[str] = ["## Stack", ""]

    if not deps:
        lines.append("  (no dependencies)")
        return "\n".join(lines)

    # Detect frameworks
    detected: list[str] = []
    for dep in deps:
        dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].split("~=")[0].split("[")[0].strip().lower()
        if dep_name in _KNOWN_FRAMEWORKS:
            detected.append(_KNOWN_FRAMEWORKS[dep_name])

    if detected:
        lines.append(f"  Frameworks: {', '.join(detected)}")

    lines.append(f"  Dependencies ({len(deps)}):")
    for dep in deps:
        lines.append(f"    - {dep}")

    return "\n".join(lines)


def _section_tool_config(config: dict | None) -> str:
    if config is None:
        return "## Tool Config\n\n(no pyproject.toml)"

    lines: list[str] = ["## Tool Config", ""]

    # ty
    ty_config = config.get("tool", {}).get("ty", {})
    if ty_config:
        lines.append("  [ty] Type Checker")
        env = ty_config.get("environment", {})
        if env.get("python-version"):
            lines.append(f"    python-version: {env['python-version']}")
        rules = ty_config.get("rules", {})
        if rules:
            errors = sorted(k for k, v in rules.items() if v == "error")
            warns = sorted(k for k, v in rules.items() if v == "warn")
            ignored = sorted(k for k, v in rules.items() if v == "ignore")
            if errors:
                lines.append(f"    error ({len(errors)}): {', '.join(errors)}")
            if warns:
                lines.append(f"    warn ({len(warns)}): {', '.join(warns)}")
            if ignored:
                lines.append(f"    ignore ({len(ignored)}): {', '.join(ignored)}")
        else:
            lines.append("    (sin reglas explícitas — defaults)")
    else:
        lines.append("  [ty] No configurado")

    # ruff
    ruff_config = config.get("tool", {}).get("ruff", {})
    if ruff_config:
        lines.append("\n  [ruff] Linter + Formatter")
        if ruff_config.get("target-version"):
            lines.append(f"    target-version: {ruff_config['target-version']}")
        if ruff_config.get("line-length"):
            lines.append(f"    line-length: {ruff_config['line-length']}")
        lint = ruff_config.get("lint", {})
        select = lint.get("select", [])
        ignore = lint.get("ignore", [])
        if select:
            lines.append(f"    select ({len(select)}): {', '.join(select)}")
        if ignore:
            lines.append(f"    ignore ({len(ignore)}): {', '.join(ignore)}")
    else:
        lines.append("\n  [ruff] No configurado")

    # hooks
    hooks_config = config.get("tool", {}).get("python-code-mcp", {}).get("hooks", {})
    if hooks_config:
        lines.append("\n  [hooks] Block config")
        lines.append(f"    block-mode: {hooks_config.get('block-mode', 'off')}")
        lines.append(f"    block-severity: {hooks_config.get('block-severity', 1)}")
        block_rules = hooks_config.get("block-rules", [])
        if block_rules:
            lines.append(f"    block-rules: {', '.join(block_rules)}")
        else:
            lines.append("    block-rules: (all)")
        lines.append(f"    block-cross-file: {hooks_config.get('block-cross-file', True)}")

    return "\n".join(lines)


async def _section_health(
    mode: str,
    ctx: Context,
) -> str:
    lines: list[str] = ["## Health", ""]

    import ty_lsp.app as app

    ts = app.ts_index
    if ts is not None:
        indexed_files = len(ts._tree_cache)
        unique_symbols = len(ts._symbols)
        lines.append(f"  tree-sitter indexed files: {indexed_files}")
        lines.append(f"  unique symbols: {unique_symbols}")
    else:
        lines.append("  tree-sitter: not available")

    open_count = len(app.open_files)
    lines.append(f"  LSP open files: {open_count}")

    if mode == "fresh":
        try:
            ty: TyServer = ctx.lifespan_context["ty"]
            ruff: RuffServer = ctx.lifespan_context["ruff"]

            ty_errors = 0
            ty_warnings = 0
            ruff_errors = 0
            ruff_warnings = 0

            # ty: use workspace_diagnostic for a single bulk call
            ws_diags = await ty.workspace_diagnostic()
            for diags in ws_diags.values():
                for d in diags:
                    sev = d.get("severity", 0)
                    if sev == 1:
                        ty_errors += 1
                    elif sev == 2:
                        ty_warnings += 1

            # ruff: collect push diagnostics (single bulk drain)
            ruff_diags = await ruff.collect_push_diagnostics(timeout=2.0)
            for diags in ruff_diags.values():
                for d in diags:
                    sev = d.get("severity", 0)
                    if sev == 1:
                        ruff_errors += 1
                    elif sev == 2:
                        ruff_warnings += 1

            lines.append(f"  ty errors: {ty_errors}, warnings: {ty_warnings}")
            lines.append(f"  ruff errors: {ruff_errors}, warnings: {ruff_warnings}")
        except Exception as e:
            lines.append(f"  (fresh diagnostics unavailable: {type(e).__name__}: {e})")

    return "\n".join(lines)


def _section_public_api(
    depth: str,
    max_symbols: int,
    py_files: list[Path],
    config: dict | None,
) -> str:
    lines: list[str] = ["## Public API", ""]

    main_pkg = _find_main_package(config or {})
    if main_pkg is None:
        lines.append("  (no Python package found)")
        return "\n".join(lines)

    init_files: list[Path] = []
    if depth == "top_level":
        init_path = main_pkg / "__init__.py"
        if init_path.exists():
            init_files.append(init_path)
    else:  # all_packages
        for py_file in py_files:
            if py_file.name == "__init__.py":
                init_files.append(py_file)

    if not init_files:
        lines.append("  (no __init__.py files found)")
        return "\n".join(lines)

    total = 0
    for init_file in init_files:
        try:
            tree, _source = _parse_file(str(init_file))
        except OSError:
            continue

        symbols = _walk_symbols(tree.root_node)
        top_level = [s for s in symbols if s.parent is None]

        if not top_level:
            continue

        rel = init_file.relative_to(Path.cwd())
        lines.append(f"  {rel}:")

        for sym in top_level:
            if total >= max_symbols:
                lines.append(f"    ... ({len(top_level)} symbols total, capped at {max_symbols})")
                break
            kind_label = "class" if sym.kind == "class" else "def"
            lines.append(f"    {kind_label} {sym.name}")
            total += 1

        if total >= max_symbols:
            break

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool MCP
# ---------------------------------------------------------------------------


@mcp.tool
async def project_overview(
    ctx: Context,
    include: list[str] | None = None,
    public_api_depth: str = "top_level",
    health_mode: str = "cached",
    max_symbols_per_section: int = 50,
) -> str:
    """Generate a comprehensive snapshot of the Python project.

    Returns metadata, structure, entry points, dependencies, tool config,
    health diagnostics, and public API — all in a single call.

    Args:
        ctx: MCP context (auto-injected).
        include: Sections to include. None = all. Values: metadata, structure,
            entry_points, stack, tool_config, health, public_api
        public_api_depth: "top_level" (main package __init__.py only) or
            "all_packages" (all __init__.py files).
        health_mode: "cached" (in-memory data) or "fresh" (live LSP diagnostics).
        max_symbols_per_section: Max symbols per section (1-500, default 50).
    """
    # Validate params
    if include is not None:
        invalid = [s for s in include if s not in _VALID_SECTIONS]
        if invalid:
            return f"Invalid section(s): {', '.join(invalid)}. Valid: {', '.join(_VALID_SECTIONS)}"
        sections = include
    else:
        sections = list(_VALID_SECTIONS)

    max_symbols = max(1, min(500, max_symbols_per_section))

    config = _load_pyproject()
    py_files = _walk_py_files()

    parts: list[str] = []

    if "metadata" in sections:
        parts.append(_section_metadata(config, py_files))

    if "structure" in sections:
        parts.append(_section_structure(py_files))

    if "entry_points" in sections:
        parts.append(_section_entry_points(config))

    if "stack" in sections:
        parts.append(_section_stack(config))

    if "tool_config" in sections:
        parts.append(_section_tool_config(config))

    if "health" in sections:
        parts.append(await _section_health(health_mode, ctx))

    if "public_api" in sections:
        parts.append(_section_public_api(public_api_depth, max_symbols, py_files, config))

    return "\n\n".join(parts)
