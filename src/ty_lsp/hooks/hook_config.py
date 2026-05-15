"""
hook_config.py — Lee la configuración de hooks desde pyproject.toml.

Usado por los hooks (scripts independientes) para saber si deben bloquear
ediciones según las reglas configuradas en [tool.python-code-mcp.hooks].
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def _find_pyproject_toml(file_path: str) -> Path | None:
    """Busca pyproject.toml subiendo desde el directorio del archivo editado."""
    start = Path(file_path).resolve().parent
    for parent in [start, *start.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            return candidate
    return None


def _load_toml(path: Path) -> dict[str, Any]:
    """Carga un archivo TOML."""
    with path.open("rb") as f:
        return tomllib.load(f)


class HookConfig:
    """Configuración de hooks extraída de [tool.python-code-mcp.hooks]."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.block_mode: str = data.get("block-mode", "off")
        self.block_severity: int = data.get("block-severity", 1)
        self.block_rules: set[str] = set(data.get("block-rules", []))
        self.block_cross_file: bool = data.get("block-cross-file", True)

    @classmethod
    def from_file(cls, file_path: str) -> HookConfig:
        """Lee la configuración buscando pyproject.toml desde el archivo editado."""
        toml_path = _find_pyproject_toml(file_path)
        if toml_path is None:
            return cls()

        config = _load_toml(toml_path)
        hooks_cfg = config.get("tool", {}).get("python-code-mcp", {}).get("hooks", {})
        return cls(hooks_cfg)

    @property
    def blocking_enabled(self) -> bool:
        """True si el bloqueo está activado (cualquier modo que no sea 'off')."""
        return self.block_mode != "off"

    def should_block_diag(self, diag: dict) -> bool:
        """Determina si un diagnóstico individual debe causar bloqueo.

        Lee el campo 'source' del diagnóstico ("ty" o "ruff") para
        filtrar según block_mode.
        """
        if not self.blocking_enabled:
            return False

        source = diag.get("source", "ty")

        # Filtrar por source según block_mode
        if self.block_mode == "ty" and source != "ty":
            return False
        if self.block_mode == "ruff" and source != "ruff":
            return False
        # "all" → ambos sources bloquean

        # Filtrar por severidad
        severity = diag.get("severity", 0)
        if severity > self.block_severity:
            return False

        # Filtrar por regla (whitelist)
        if self.block_rules:
            code = str(diag.get("code", ""))
            if code not in self.block_rules:
                return False

        return True

    def filter_blocking(self, diags: list[dict]) -> list[dict]:
        """Filtra una lista de diagnósticos, retornando solo los que bloquean."""
        return [d for d in diags if self.should_block_diag(d)]
