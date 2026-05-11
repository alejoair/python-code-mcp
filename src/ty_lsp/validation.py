"""Validación de archivos Python y gestión de archivos abiertos en ty."""

import sys
from pathlib import Path

from fastmcp import Context  # type: ignore[import-unresolved]

from ty_lsp.gitignore import is_ignored, parse_gitignore
from ty_lsp.lsp import TyServer


class FileError(Exception):
    """Raised when a file path fails validation for LSP operations."""


def validate_py_file(file_path: str) -> Path:
    """Valida que file_path exista y sea .py. Lanza FileError si no."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileError(f"Error: el archivo no existe: {file_path}")
    if not path.suffix == ".py":
        raise FileError(f"Error: el archivo no es Python: {file_path}")
    return path


async def ensure_file_open(ctx: Context, file_path: str) -> str:
    """Valida file_path y asegura que ty lo tenga abierto via didOpen.

    Retorna el file URI. Lanza FileError si el path es inválido.
    """
    ty: TyServer = ctx.lifespan_context["ty"]
    open_files: dict[str, int] = ctx.lifespan_context["open_files"]

    path = validate_py_file(file_path)

    file_uri = path.as_uri()
    if file_uri not in open_files:
        content = path.read_text(encoding="utf-8")
        await ty.open_file(file_uri, content)
        open_files[file_uri] = 1

    return file_uri


async def open_project_files(
    ty: TyServer, root: Path, patterns: list[tuple[str, bool]] | None = None
) -> dict[str, int]:
    """Abre todos los archivos .py del proyecto en ty via didOpen.

    Respeta .gitignore. Retorna dict de URI → versión.
    """
    if patterns is None:
        patterns = parse_gitignore(root)

    py_files: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if is_ignored(rel, patterns):
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
