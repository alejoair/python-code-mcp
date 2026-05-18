"""
install.py — Registra python-code-mcp como servidor MCP en Claude Code,
copia los hooks y configura .claude/settings.json del proyecto.

Ejecución: python-code-mcp install
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_claude_cli() -> str | None:
    """Busca el CLI de Claude en el PATH."""
    return shutil.which("claude")


def _install_hooks() -> None:
    """Copia los hooks al directorio .claude/hooks/ del proyecto y actualiza settings.json."""
    hooks_src = Path(__file__).parent / "hooks"
    project_root = Path.cwd()
    hooks_dst = project_root / ".claude" / "hooks"
    hooks_dst.mkdir(parents=True, exist_ok=True)

    # Copiar scripts de hooks
    for src_name, dst_name in [
        ("pre_tool_use.py", "python-code-mcp-pre.py"),
        ("post_tool_use.py", "python-code-mcp-post.py"),
        ("pre_tool_use_edit.py", "python-code-mcp-pre-edit.py"),
        ("post_tool_use_edit.py", "python-code-mcp-post-edit.py"),
    ]:
        src = hooks_src / src_name
        dst = hooks_dst / dst_name
        shutil.copy2(src, dst)
        print(f"[OK] Hook copiado: {dst}")

    # Ruta absoluta en formato posix para los comandos
    hooks_dir_posix = hooks_dst.as_posix()
    pre_cmd = f"python {hooks_dir_posix}/python-code-mcp-pre.py"
    post_cmd = f"python {hooks_dir_posix}/python-code-mcp-post.py"

    new_pre_entry = {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": pre_cmd}],
    }
    new_post_entry = {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": post_cmd}],
    }

    edit_pre_cmd = f"python {hooks_dir_posix}/python-code-mcp-pre-edit.py"
    edit_post_cmd = f"python {hooks_dir_posix}/python-code-mcp-post-edit.py"

    new_edit_pre_entry = {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": edit_pre_cmd}],
    }

    new_edit_post_entry = {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": edit_post_cmd}],
    }

    # Leer/crear .claude/settings.json del proyecto
    settings_path = project_root / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})

    # Mergear PreToolUse: reemplazar entradas python-code-mcp, preservar el resto
    pre_entries = [
        e for e in hooks.get("PreToolUse", [])
        if not _is_our_hook(e)
    ]
    pre_entries.append(new_pre_entry)
    pre_entries.append(new_edit_pre_entry)
    hooks["PreToolUse"] = pre_entries

    # Mergear PostToolUse: igual
    post_entries = [
        e for e in hooks.get("PostToolUse", [])
        if not _is_our_hook(e)
    ]
    post_entries.append(new_post_entry)
    post_entries.append(new_edit_post_entry)
    hooks["PostToolUse"] = post_entries

    settings_path.write_text(
        json.dumps(settings, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] settings.json actualizado: {settings_path}")


def _is_our_hook(entry: dict) -> bool:
    """Detecta si una entrada de hook pertenece a python-code-mcp."""
    for h in entry.get("hooks", []):
        cmd = h.get("command", "")
        if "python-code-mcp-pre" in cmd or "python-code-mcp-post" in cmd:
            return True
    return False


def _install_agents() -> None:
    """Copia los agentes .md al directorio .claude/agents/ del proyecto."""
    agents_src = Path(__file__).parent / "agents"
    project_root = Path.cwd()
    agents_dst = project_root / ".claude" / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)

    for agent_file in sorted(agents_src.glob("*.md")):
        dst = agents_dst / agent_file.name
        shutil.copy2(agent_file, dst)
        print(f"[OK] Agente copiado: {dst}")


def main() -> None:
    """Registra python-code-mcp como servidor MCP en Claude Code."""
    claude = find_claude_cli()
    if claude is None:
        print("Error: no se encontró el CLI de Claude ('claude').")
        print("Instálalo con: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    url = "http://127.0.0.1:8000/mcp"

    cmd = [
        claude, "mcp", "add",
        "-s", "project",
        "-t", "http",
        "python-code-mcp",
        url,
    ]

    print("Ejecutando: " + " ".join(cmd))
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n[OK] Servidor MCP 'python-code-mcp' registrado exitosamente.")
        print("     Transporte HTTP en " + url)
        print("     Inicia el servidor con: python-code-mcp")
    else:
        print("\n[ERROR] No se pudo registrar el servidor (codigo %d)." % result.returncode)
        sys.exit(result.returncode)

    _install_hooks()
    _install_agents()


def run_install() -> None:
    """Alias para ser llamado desde server.py."""
    main()


if __name__ == "__main__":
    main()
