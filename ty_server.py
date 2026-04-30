"""
ty_server.py — Lanza ty server como subprocess y queda a la espera.

Lanza `ty server` con asyncio.create_subprocess_exec y expone
funciones async para enviar mensajes JSON-RPC y recibir respuestas.

El protocolo LSP usa JSON-RPC 2.0 sobre stdio con framing:
    Content-Length: <N>\r\n\r\n<json_payload>
"""

import asyncio
import json
import sys


class TyServer:
    """Cliente LSP para el servidor ty."""

    def __init__(self, root_uri: str | None = None):
        self.process: asyncio.subprocess.Process | None = None
        self._msg_id = 0
        self._reader_task: asyncio.Task | None = None
        self.root_uri = root_uri

    async def start(self, *, auto_read: bool = True) -> None:
        """Lanza `ty server` como subprocess.

        Args:
            auto_read: Si True, arranca un loop en background que lee e
                imprime las respuestas automáticamente. Si False, el
                llamador debe llamar a read_message() manualmente.
        """
        self.process = await asyncio.create_subprocess_exec(
            "ty", "server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        print(f"[ty_server] Proceso iniciado (PID: {self.process.pid})")

        # Arrancar task en background para leer stderr
        asyncio.create_task(self._read_stderr())

        if auto_read:
            # Arrancar task en background para imprimir respuestas
            self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_stderr(self) -> None:
        """Lee stderr de ty y lo imprime."""
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            print(f"[ty stderr] {line.decode().rstrip()}", file=sys.stderr)

    async def _read_loop(self) -> None:
        """Lee respuestas de ty stdout y las imprime."""
        assert self.process and self.process.stdout
        while True:
            response = await self.read_message()
            if response is None:
                print("[ty_server] ty cerró la conexión")
                break
            print(f"\n[ty response] {json.dumps(response, indent=2)}\n")

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
        print(f"[ty send] {json.dumps(message, indent=2)}")

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
        imprimen pero se descartan. Solo retorna la respuesta con el ID
        del request enviado.
        """
        msg_id = await self.send_request(method, params)
        while True:
            msg = await asyncio.wait_for(self.read_message(), timeout=timeout)
            if msg is None:
                raise ConnectionError("ty cerró la conexión")
            # Si es la respuesta a nuestro request
            if "id" in msg and msg["id"] == msg_id:
                return msg
            # Es una notificación, imprimir y seguir
            print(f"[ty notification] {json.dumps(msg, indent=2)}")

    async def stop(self) -> None:
        """Detiene el servidor ty."""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            print("[ty_server] Proceso terminado")


async def main() -> None:
    """Main — lanza ty y queda a la espera."""
    server = TyServer()
    await server.start()
    print("[ty_server] Listo. Presiona Ctrl+C para detener.")
    try:
        # Queda vivo hasta Ctrl+C
        await server._reader_task
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
