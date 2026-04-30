"""
lsp.py — Cliente LSP para ty server.

Maneja toda la comunicación con `ty server` via subprocess:
- Transporte: stdio (stdin/stdout) con framing LSP (Content-Length)
- Protocolo: JSON-RPC 2.0
"""

import asyncio
import json
import sys


class TyServer:
    """Cliente LSP para el servidor ty."""

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self._msg_id = 0
        self._stderr_task: asyncio.Task | None = None
        self._initialized = False

    async def start(self) -> None:
        """Lanza `ty server` como subprocess."""
        self.process = await asyncio.create_subprocess_exec(
            "ty", "server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        """Lee stderr de ty y lo redirige a nuestro stderr."""
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            print(f"[ty stderr] {line.decode().rstrip()}", file=sys.stderr)

    async def read_message(self) -> dict | None:
        """Lee un mensaje LSP del stdout de ty (framing con Content-Length)."""
        assert self.process and self.process.stdout

        # Leer headers hasta línea vacía
        headers: dict[str, str] = {}
        while True:
            line_bytes = await self.process.stdout.readline()
            if not line_bytes:
                return None
            line = line_bytes.decode().strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

        # Obtener Content-Length
        content_length = int(headers.get("Content-Length", 0))
        if content_length == 0:
            return None

        # Leer el body
        body_bytes = await self.process.stdout.read(content_length)
        return json.loads(body_bytes)

    async def send(self, message: dict) -> None:
        """Envía un mensaje JSON-RPC a ty via stdin con framing LSP."""
        assert self.process and self.process.stdin

        body = json.dumps(message)
        body_bytes = body.encode("utf-8")
        header = f"Content-Length: {len(body_bytes)}\r\n\r\n"

        self.process.stdin.write(header.encode("utf-8") + body_bytes)
        await self.process.stdin.drain()

    def next_id(self) -> int:
        """Genera el siguiente ID de mensaje JSON-RPC."""
        self._msg_id += 1
        return self._msg_id

    async def send_request(self, method: str, params: dict | None = None) -> int:
        """Envía un request JSON-RPC y retorna el ID usado."""
        msg_id = self.next_id()
        message: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            message["params"] = params
        await self.send(message)
        return msg_id

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        """Envía una notificación JSON-RPC (sin ID, no espera respuesta)."""
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self.send(message)

    async def send_and_wait(
        self, method: str, params: dict | None = None, *, timeout: float = 10.0
    ) -> dict:
        """Envía un request y lee hasta encontrar la respuesta con el ID correcto.

        Las notificaciones (diagnostics, etc.) que lleguen entremedio se
        descartan. Solo retorna la respuesta con el ID del request enviado.
        """
        msg_id = await self.send_request(method, params)
        while True:
            msg = await asyncio.wait_for(self.read_message(), timeout=timeout)
            if msg is None:
                raise ConnectionError("ty cerró la conexión")
            if "id" in msg and msg["id"] == msg_id:
                return msg

    async def initialize(self, root_uri: str) -> dict:
        """Inicializa la comunicación LSP con ty.

        Ejecuta los 2 pasos obligatorios:
        1. initialize (request) — handshake con capabilities
        2. initialized (notificación) — confirma la inicialización
        """
        resp = await self.send_and_wait("initialize", {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {},
        })
        await self.send_notification("initialized", {})
        self._initialized = True
        return resp

    async def open_file(self, file_uri: str, content: str, version: int = 1) -> None:
        """Notifica a ty que un archivo está abierto."""
        await self.send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": "python",
                "version": version,
                "text": content,
            }
        })

    async def hover(self, file_uri: str, line: int, character: int) -> dict | None:
        """Solicita hover info sobre una posición del archivo.

        Args:
            file_uri: URI del archivo (ej: file:///C:/path/to/file.py)
            line: Línea (0-indexed)
            character: Columna (0-indexed, UTF-16)

        Returns:
            Respuesta del hover o None si no hay info.
        """
        resp = await self.send_and_wait("textDocument/hover", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })

        result = resp.get("result")
        if result is None or (isinstance(result, dict) and result.get("contents") is None):
            return None
        return result

    async def stop(self) -> None:
        """Detiene el servidor ty."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            self.process = None
            self._initialized = False
