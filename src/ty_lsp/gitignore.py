"""Utilidades para parsear y evaluar patrones .gitignore."""

import fnmatch
from pathlib import Path


def parse_gitignore(root: Path) -> list[tuple[str, bool]]:
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


def is_ignored(rel_path: str, patterns: list[tuple[str, bool]]) -> bool:
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
