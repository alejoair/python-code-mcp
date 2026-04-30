"""Test del flujo completo LSP: init, open, hover."""
import asyncio
import json
from pathlib import Path
from ty_server import TyServer


async def test():
    server = TyServer()
    await server.start(auto_read=False)

    # 1. Initialize
    root = str(Path.cwd())
    root_uri = Path(root).as_uri()
    resp = await server.send_and_wait("initialize", {
        "processId": None,
        "rootUri": root_uri,
        "capabilities": {},
    })
    print("INIT OK:", resp.get("result", {}).get("serverInfo"))

    # 2. Initialized notification
    await server.send_notification("initialized", {})

    # 3. didOpen
    content = Path("sample.py").read_text(encoding="utf-8")
    file_uri = Path("sample.py").resolve().as_uri()
    await server.send_notification("textDocument/didOpen", {
        "textDocument": {
            "uri": file_uri,
            "languageId": "python",
            "version": 1,
            "text": content,
        }
    })
    await asyncio.sleep(1)

    # 4. Hover sobre 'greet' (linea 3, col 4)
    resp = await server.send_and_wait("textDocument/hover", {
        "textDocument": {"uri": file_uri},
        "position": {"line": 3, "character": 4},
    })
    print("\nHOVER on 'greet':")
    print(json.dumps(resp, indent=2))

    # 5. Hover sobre 'result' (linea 7, col 0)
    resp2 = await server.send_and_wait("textDocument/hover", {
        "textDocument": {"uri": file_uri},
        "position": {"line": 7, "character": 0},
    })
    print("\nHOVER on 'result':")
    print(json.dumps(resp2, indent=2))

    await server.stop()


if __name__ == "__main__":
    asyncio.run(test())
