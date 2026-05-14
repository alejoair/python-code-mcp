"""Instancia central de FastMCP y estado global del servidor."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP  # type: ignore[import-unresolved]

if TYPE_CHECKING:
    from ty_lsp.lsp import RuffServer, TyServer
    from ty_lsp.treesitter import TreeSitterIndex


def _print_configured_rules(root_path: Path) -> None:
    """Lee pyproject.toml y muestra las reglas configuradas de ty y ruff."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redefine]

    toml_path = root_path / "pyproject.toml"
    if not toml_path.exists():
        print("[python-code-mcp] No se encontró pyproject.toml", file=sys.stderr)
        return

    try:
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
    except Exception as e:
        print(f"[python-code-mcp] Error leyendo pyproject.toml: {e}", file=sys.stderr)
        return

    print("\n" + "=" * 60, file=sys.stderr)
    print(" python-code-mcp — Reglas configuradas", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # ty rules
    ty_rules = config.get("tool", {}).get("ty", {}).get("rules", {})
    ty_env = config.get("tool", {}).get("ty", {}).get("environment", {})
    if ty_rules or ty_env:
        print("\n[ty] Type Checker", file=sys.stderr)
        if ty_env.get("python-version"):
            print(f"  python-version: {ty_env['python-version']}", file=sys.stderr)
        if ty_rules:
            errors = {k: v for k, v in ty_rules.items() if v == "error"}
            warns = {k: v for k, v in ty_rules.items() if v == "warn"}
            ignored = {k: v for k, v in ty_rules.items() if v == "ignore"}
            if errors:
                print(f"  error ({len(errors)}):", file=sys.stderr)
                for rule in sorted(errors):
                    print(f"    - {rule}", file=sys.stderr)
            if warns:
                print(f"  warn ({len(warns)}):", file=sys.stderr)
                for rule in sorted(warns):
                    print(f"    - {rule}", file=sys.stderr)
            if ignored:
                print(f"  ignore ({len(ignored)}):", file=sys.stderr)
                for rule in sorted(ignored):
                    print(f"    - {rule}", file=sys.stderr)
        else:
            print("  (sin reglas explícitas — defaults)", file=sys.stderr)
    else:
        print("\n[ty] No configurado en pyproject.toml", file=sys.stderr)

    # ruff rules
    ruff_lint = config.get("tool", {}).get("ruff", {}).get("lint", {})
    ruff_base = config.get("tool", {}).get("ruff", {})
    if ruff_lint or ruff_base:
        print("\n[ruff] Linter + Formatter", file=sys.stderr)
        if ruff_base.get("target-version"):
            print(f"  target-version: {ruff_base['target-version']}", file=sys.stderr)
        if ruff_base.get("line-length"):
            print(f"  line-length: {ruff_base['line-length']}", file=sys.stderr)
        select = ruff_lint.get("select", [])
        ignore = ruff_lint.get("ignore", [])
        if select:
            print(f"  select ({len(select)}): {', '.join(select)}", file=sys.stderr)
        if ignore:
            print(f"  ignore ({len(ignore)}): {', '.join(ignore)}", file=sys.stderr)
    else:
        print("\n[ruff] No configurado en pyproject.toml", file=sys.stderr)

    print("\n" + "=" * 60 + "\n", file=sys.stderr)


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Lifespan que inicia y detiene ty y ruff como subprocess LSP."""
    # Importaciones diferidas para evitar ciclos (estos modulos no importan app.py)
    from ty_lsp.lsp import RuffServer, TyServer
    from ty_lsp.lsp_helpers import uri_to_path
    from ty_lsp.treesitter import TreeSitterIndex
    from ty_lsp.validation import open_project_files, parse_gitignore

    import ty_lsp.app as app

    root_path = Path.cwd()
    root_uri = root_path.as_uri()

    patterns = parse_gitignore(root_path)

    # Iniciar ty (type checker)
    ty = TyServer()
    await ty.start()
    await ty.initialize(root_uri)

    open_files = await open_project_files(ty, root_path, patterns)

    # Iniciar ruff (linter + formatter)
    ruff = RuffServer()
    await ruff.start()
    await ruff.initialize(root_uri)

    # Abrir los mismos archivos en ruff
    for uri in open_files:
        file_path_str = uri_to_path(uri)
        try:
            content = Path(file_path_str).read_text(encoding="utf-8")
            await ruff.open_file(uri, content)
        except OSError:
            pass

    ts_index = TreeSitterIndex()
    ts_index.build(root_path, patterns)

    app.ty_server = ty
    app.ruff_server = ruff
    app.open_files = open_files
    app.ts_index = ts_index

    _print_configured_rules(root_path)

    print(
        "[python-code-mcp] Lifespan iniciado: ty + ruff + tree-sitter",
        file=sys.stderr,
    )

    yield {
        "ty": ty,
        "ruff": ruff,
        "open_files": open_files,
        "ts_index": ts_index,
    }

    await ruff.stop()
    await ty.stop()
    app.ty_server = None
    app.ruff_server = None
    app.open_files = {}
    app.ts_index = None


mcp = FastMCP(
    name="python-code-mcp",
    instructions=(
        "Servidor MCP que expone funcionalidades del type checker ty "
        "y el linter/formatter ruff via Language Server Protocol. "
        "Ty proporciona inferencia de tipos, diagnósticos y más para archivos Python. "
        "Ruff proporciona formateo, linting y code actions."
    ),
    lifespan=_lifespan,
)

# Estado global accesible por las rutas HTTP custom
ty_server: TyServer | None = None
ruff_server: RuffServer | None = None
open_files: dict[str, int] = {}
ts_index: TreeSitterIndex | None = None
