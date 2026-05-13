"""
lsp.py — Clientes LSP para servidores de lenguaje Python.

Maneja la comunicación LSP via subprocess:
- Transporte: stdio (stdin/stdout) con framing LSP (Content-Length)
- Protocolo: JSON-RPC 2.0

Clases:
- LSPClient: clase base genérica para cualquier servidor LSP sobre stdio.
- TyServer: cliente para el type checker ty (hover, diagnostics, definition, etc.).
- RuffServer: cliente para ruff (formatting, linting, code actions).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import ClassVar


class LSPClient:
    """Cliente LSP genérico sobre stdio (stdin/stdout).

    Implementa el protocolo JSON-RPC 2.0 con framing Content-Length.
    Las subclases deben sobrescribir ``initialize()`` con las capabilities
    específicas del servidor.
    """

    # Prefijo para logs de stderr (sobrescribir en subclases)
    _log_prefix: ClassVar[str] = "lsp"

    def __init__(self, command: str, args: list[str]) -> None:
        self._command = command
        self._args = args
        self.process: asyncio.subprocess.Process | None = None
        self._msg_id = 0
        self._stderr_task: asyncio.Task | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Lanza el servidor LSP como subprocess."""
        self.process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        """Lee stderr del servidor y lo redirige a nuestro stderr."""
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            print(
                f"[{self._log_prefix} stderr] {line.decode().rstrip()}",
                file=sys.stderr,
            )

    async def read_message(self) -> dict | None:
        """Lee un mensaje LSP del stdout (framing con Content-Length)."""
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
        """Envía un mensaje JSON-RPC via stdin con framing LSP."""
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

        Usa un lock para evitar lecturas concurrentes de stdout.
        """
        async with self._lock:
            msg_id = await self.send_request(method, params)
            while True:
                msg = await asyncio.wait_for(self.read_message(), timeout=timeout)
                if msg is None:
                    raise ConnectionError(
                        f"{self._log_prefix} cerró la conexión"
                    )
                if "id" in msg and msg["id"] == msg_id:
                    return msg

    async def initialize(self, root_uri: str) -> dict:
        """Inicializa la comunicación LSP.

        Sobrescribir en subclases para personalizar capabilities.
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
        """Notifica que un archivo está abierto."""
        await self.send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": "python",
                "version": version,
                "text": content,
            }
        })

    async def change_file(self, file_uri: str, content: str, version: int) -> None:
        """Notifica que el contenido de un archivo abierto ha cambiado."""
        await self.send_notification("textDocument/didChange", {
            "textDocument": {"uri": file_uri, "version": version},
            "contentChanges": [{"text": content}],
        })

    async def close_file(self, file_uri: str) -> None:
        """Notifica que un archivo fue cerrado."""
        await self.send_notification("textDocument/didClose", {
            "textDocument": {"uri": file_uri},
        })

    async def stop(self) -> None:
        """Detiene el servidor LSP."""
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()
            self.process = None
            self._initialized = False


class TyServer(LSPClient):
    """Cliente LSP para el type checker ty."""

    _log_prefix: ClassVar[str] = "ty"

    def __init__(self) -> None:
        super().__init__("ty", ["server"])

    async def initialize(self, root_uri: str) -> dict:
        """Inicializa ty con capabilities específicas."""
        resp = await self.send_and_wait("initialize", {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {},
        })
        await self.send_notification("initialized", {})
        self._initialized = True
        return resp

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

    async def workspace_diagnostic(self) -> dict[str, list[dict]]:
        """Recolecta diagnósticos de todo el workspace via publishDiagnostics.

        ty usa el modelo push: tras abrir archivos, envía notificaciones
        textDocument/publishDiagnostics con los diagnósticos de cada archivo.
        Este método lee todas las notificaciones pendientes y las agrupa por URI.

        Returns:
            Dict de URI → lista de diagnósticos.
        """
        async with self._lock:
            all_diags: dict[str, list[dict]] = {}
            for _ in range(500):
                try:
                    msg = await asyncio.wait_for(self.read_message(), timeout=5.0)
                except asyncio.TimeoutError:
                    break
                if msg is None:
                    break
                if msg.get("method") == "textDocument/publishDiagnostics":
                    params = msg.get("params", {})
                    uri = params.get("uri", "")
                    diags = params.get("diagnostics", [])
                    if diags:
                        all_diags[uri] = diags
            return all_diags

    async def diagnostic(self, file_uri: str) -> list[dict]:
        """Solicita diagnósticos (type check) para un archivo (pull model).

        Args:
            file_uri: URI del archivo.

        Returns:
            Lista de diagnósticos (puede estar vacía).
        """
        resp = await self.send_and_wait("textDocument/diagnostic", {
            "textDocument": {"uri": file_uri},
        })

        result = resp.get("result")
        if result is None:
            return []
        items = result.get("items", [])
        return items

    async def definition(
        self, file_uri: str, line: int, character: int
    ) -> list[dict]:
        """Salta a la definición de un símbolo.

        Args:
            file_uri: URI del archivo.
            line: Línea (0-indexed).
            character: Columna (0-indexed).

        Returns:
            Lista de locaciones.
        """
        resp = await self.send_and_wait("textDocument/definition", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })

        result = resp.get("result")
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    async def references(
        self, file_uri: str, line: int, character: int
    ) -> list[dict]:
        """Busca todas las referencias a un símbolo.

        Args:
            file_uri: URI del archivo.
            line: Línea (0-indexed).
            character: Columna (0-indexed).

        Returns:
            Lista de locaciones con referencias.
        """
        resp = await self.send_and_wait("textDocument/references", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True},
        })

        result = resp.get("result")
        if result is None:
            return []
        return result

    async def rename(
        self, file_uri: str, line: int, character: int, new_name: str
    ) -> dict | None:
        """Renombra un símbolo en todo el workspace.

        Args:
            file_uri: URI del archivo.
            line: Línea (0-indexed).
            character: Columna (0-indexed).
            new_name: Nuevo nombre para el símbolo.

        Returns:
            WorkspaceEdit con los cambios, o None si no se pudo renombrar.
        """
        resp = await self.send_and_wait("textDocument/rename", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
            "newName": new_name,
        })

        result = resp.get("result")
        if result is None:
            return None
        return result


class RuffServer(LSPClient):
    """Cliente LSP para ruff (linter + formatter)."""

    _log_prefix: ClassVar[str] = "ruff"

    def __init__(self) -> None:
        super().__init__("ruff", ["server"])

    async def initialize(self, root_uri: str) -> dict:
        """Inicializa ruff con capabilities específicas."""
        resp = await self.send_and_wait("initialize", {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                        "versionSupport": True,
                    },
                    "formatting": {"dynamicRegistration": False},
                    "codeAction": {
                        "dynamicRegistration": False,
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    "quickfix",
                                    "source.fixAll",
                                    "source.organizeImports",
                                ]
                            }
                        },
                    },
                },
            },
        })
        await self.send_notification("initialized", {})
        self._initialized = True
        return resp

    async def format_file(self, file_uri: str) -> list[dict]:
        """Formatea un archivo con ruff.

        Args:
            file_uri: URI del archivo.

        Returns:
            Lista de TextEdit con los cambios de formato.
        """
        resp = await self.send_and_wait("textDocument/formatting", {
            "textDocument": {"uri": file_uri},
            "options": {"tabSize": 4, "insertSpaces": True},
        })

        result = resp.get("result")
        if result is None:
            return []
        return result

    async def diagnostic(self, file_uri: str) -> list[dict]:
        """Solicita diagnósticos de lint para un archivo (pull model).

        Args:
            file_uri: URI del archivo.

        Returns:
            Lista de diagnósticos de lint.
        """
        resp = await self.send_and_wait("textDocument/diagnostic", {
            "textDocument": {"uri": file_uri},
        })

        result = resp.get("result")
        if result is None:
            return []
        items = result.get("items", [])
        return items

    async def code_actions(
        self,
        file_uri: str,
        start_line: int,
        start_char: int,
        end_line: int,
        end_char: int,
        *,
        only: list[str] | None = None,
    ) -> list[dict]:
        """Solicita code actions para un rango del archivo.

        Args:
            file_uri: URI del archivo.
            start_line: Línea inicio (0-indexed).
            start_char: Columna inicio (0-indexed).
            end_line: Línea fin (0-indexed).
            end_char: Columna fin (0-indexed).
            only: Filtrar por kinds (ej: ["quickfix", "source.fixAll"]).

        Returns:
            Lista de CodeAction o Command.
        """
        params: dict = {
            "textDocument": {"uri": file_uri},
            "range": {
                "start": {"line": start_line, "character": start_char},
                "end": {"line": end_line, "character": end_char},
            },
            "context": {"diagnostics": []},
        }
        if only:
            params["context"]["only"] = only

        resp = await self.send_and_wait("textDocument/codeAction", params)

        result = resp.get("result")
        if result is None:
            return []
        return result

    async def collect_push_diagnostics(
        self, *, timeout: float = 3.0
    ) -> dict[str, list[dict]]:
        """Recolecta diagnósticos push (publishDiagnostics) pendientes.

        Ruff envía publishDiagnostics tras didOpen/didChange.
        Este método los drena y agrupa por URI.

        Returns:
            Dict de URI → lista de diagnósticos.
        """
        async with self._lock:
            all_diags: dict[str, list[dict]] = {}
            for _ in range(100):
                try:
                    msg = await asyncio.wait_for(
                        self.read_message(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    break
                if msg is None:
                    break
                if msg.get("method") == "textDocument/publishDiagnostics":
                    params = msg.get("params", {})
                    uri = params.get("uri", "")
                    diags = params.get("diagnostics", [])
                    all_diags[uri] = diags
            return all_diags
