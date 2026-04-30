"""
ty_client.py — Cliente interactivo para enviar mensajes JSON-RPC a ty server.

Se conecta al stdin/stdout de `ty server` y permite:
  - Enviar el handshake LSP (initialize + initialized)
  - Abrir un documento (textDocument/didOpen)
  - Pedir hover (textDocument/hover)
  - Enviar requests arbitrarios por línea de comandos

Uso:
    python ty_client.py
    # Luego escribir comandos interactivos:
    #   init                    — enviar handshake initialize + initialized
    #   open <filepath>         — abrir un archivo en ty
    #   hover <filepath> <line> <col>  — pedir hover info
    #   raw <json>              — enviar un JSON-RPC arbitrario
    #   quit                    — salir
"""

import asyncio
import json
from pathlib import Path

from ty_server import TyServer


def file_uri(path: str) -> str:
    """Convierte un path local a URI file://."""
    p = Path(path).resolve()
    return p.as_uri()


async def interactive_main() -> None:
    """Loop interactivo para enviar mensajes a ty."""
    server = TyServer()
    await server.start(auto_read=False)

    initialized = False

    print("\n=== Cliente interactivo de ty ===")
    print("Comandos:")
    print("  init                        — handshake LSP (initialize + initialized)")
    print("  open <filepath>             — abrir documento en ty")
    print("  hover <filepath> <line> <col> — pedir hover info")
    print("  raw <json>                  — enviar JSON-RPC arbitrario")
    print("  quit                        — salir")
    print()

    loop = asyncio.get_event_loop()

    try:
        while True:
            # Leer input del usuario
            line = await loop.run_in_executor(None, lambda: input("ty> ").strip())
            if not line:
                continue

            parts = line.split(maxsplit=1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            if cmd == "quit":
                break

            elif cmd == "init":
                root_uri_str = file_uri(str(Path.cwd()))
                print(f"[client] Inicializando con rootUri={root_uri_str}")

                # send_and_wait lee hasta la respuesta con ID correcto
                resp = await server.send_and_wait("initialize", {
                    "processId": None,
                    "rootUri": root_uri_str,
                    "capabilities": {},
                })
                print(f"[client] initialize response: {json.dumps(resp, indent=2)}")

                # Enviar initialized (notificación, no espera respuesta)
                await server.send_notification("initialized", {})
                initialized = True
                print("[client] Handshake completado")

            elif cmd == "open":
                if not initialized:
                    print("Error: ejecuta 'init' primero")
                    continue
                if not args:
                    print("Uso: open <filepath>")
                    continue
                filepath = args.strip()
                p = Path(filepath)
                if not p.exists():
                    print(f"Archivo no encontrado: {filepath}")
                    continue
                uri = file_uri(filepath)
                content = p.read_text(encoding="utf-8")
                await server.send_notification("textDocument/didOpen", {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": content,
                    },
                })
                # Dar tiempo a ty para procesar y enviar diagnostics
                await asyncio.sleep(1)
                # Drenar notificaciones pendientes (diagnostics)
                print("[client] Documento abierto: {uri}")

            elif cmd == "hover":
                if not initialized:
                    print("Error: ejecuta 'init' primero")
                    continue
                hover_args = args.strip().split()
                if len(hover_args) < 3:
                    print("Uso: hover <filepath> <line> <col>")
                    continue
                filepath = hover_args[0]
                line_num = int(hover_args[1])
                col_num = int(hover_args[2])
                uri = file_uri(filepath)
                resp = await server.send_and_wait("textDocument/hover", {
                    "textDocument": {"uri": uri},
                    "position": {"line": line_num, "character": col_num},
                })
                print(f"\n[hover] {json.dumps(resp, indent=2)}")

            elif cmd == "raw":
                if not args:
                    print("Uso: raw <json>")
                    continue
                try:
                    msg = json.loads(args)
                    await server.send(msg)
                except json.JSONDecodeError as e:
                    print(f"JSON inválido: {e}")

            else:
                print(f"Comando desconocido: {cmd}")

    except (EOFError, KeyboardInterrupt):
        print("\nSaliendo...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(interactive_main())
