# CLAUDE.md — Guía del proyecto

## Dependencias

Las dependencias están definidas en `pyproject.toml` con versiones exactas:

- **fastmcp** `3.2.4` — Framework para construir servidores MCP (Model Context Protocol)
- **ty** `0.0.33` — Type checker para Python, escrito en Rust por Astral

## ty como servidor LSP

### Lanzamiento

```bash
ty server
```

- **Transporte:** stdio (stdin/stdout)
- **Lenguaje:** Python únicamente
- **Detectores de raíz del proyecto:** `ty.toml`, `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt`, `.git`
- **Especificación LSP:** 3.17

### Métodos LSP soportados (20)

| Método | Descripción |
|---|---|
| `notebookDocument/*` | Soporte para Jupyter notebooks (.ipynb) |
| `textDocument/codeAction` | Quick fixes (agregar imports, eliminar supresiones) |
| `textDocument/completion` | Autocompletado con auto-import |
| `textDocument/declaration` | Ir a declaración |
| `textDocument/definition` | Ir a definición |
| `textDocument/diagnostic` | Diagnósticos (pull y push) |
| `textDocument/documentHighlight` | Resaltar ocurrencias del símbolo |
| `textDocument/documentSymbol` | Outline de símbolos del archivo |
| `textDocument/foldingRange` | Folding de código Python |
| `textDocument/hover` | Info de tipo, docs, firmas |
| `textDocument/inlayHint` | Type hints inline para variables/params |
| `textDocument/prepareRename` | Preparar renombrado |
| `textDocument/references` | Buscar todas las referencias |
| `textDocument/rename` | Renombrar símbolo en todo el workspace |
| `textDocument/selectionRange` | Expandir/contraer selección |
| `textDocument/semanticTokens` | Highlighting semántico basado en tipos |
| `textDocument/signatureHelp` | Info de parámetros al escribir `(` |
| `textDocument/typeDefinition` | Ir a definición del tipo |
| `workspace/diagnostic` | Diagnósticos de todo el workspace |
| `workspace/symbol` | Buscar símbolos en el workspace |

### Métodos LSP NO soportados (6)

- `callHierarchy/*`
- `textDocument/codeLens`
- `textDocument/documentColor`
- `textDocument/documentLink`
- `textDocument/implementation`
- `typeHierarchy/*`

### Métodos delegados a Ruff

- `textDocument/formatting`
- `textDocument/onTypeFormatting`
- `textDocument/rangeFormatting`

### Configuración vía LSP

**Opciones de inicialización** (`initialize`):

| Opción | Tipo | Default | Descripción |
|---|---|---|---|
| `logFile` | `string \| null` | `null` | Path al archivo de log |
| `logLevel` | `string` | `"info"` | `trace`, `debug`, `info`, `warn`, `error` |

**Settings del workspace** (`workspace/didChangeConfiguration`):

| Setting | Tipo | Default | Descripción |
|---|---|---|---|
| `configuration` | `object \| null` | `null` | Config inline de ty (sobreescribe archivos) |
| `configurationFile` | `string \| null` | `null` | Path a `ty.toml` (no `pyproject.toml`) |
| `disableLanguageServices` | `boolean` | `false` | Desactivar completions, hover, go-to-def, etc. |
| `diagnosticMode` | `string` | `"openFilesOnly"` | `off`, `openFilesOnly`, `workspace` |
| `showSyntaxErrors` | `boolean` | `true` | Mostrar/ocultar diagnósticos de errores de sintaxis |
| `inlayHints.variableTypes` | `boolean` | `true` | Mostrar inlay hints de tipo de variable |
| `inlayHints.callArgumentNames` | `boolean` | `true` | Mostrar nombres de argumentos en llamadas |
| `completions.autoImport` | `boolean` | `true` | Incluir sugerencias de auto-import |

### Configuración por archivo

ty lee configuración desde `ty.toml` o `[tool.ty]` en `pyproject.toml`. Secciones principales:

- **`[rules]`** — Habilitar/deshabilitar reglas con severidad (`ignore`/`warn`/`error`)
- **`[analysis]`** — `allowed-unresolved-imports`, `replace-imports-with-any`, `respect-type-ignore-comments`
- **`[environment]`** — `python` path, `python-version` (3.7–3.15), `python-platform`, `typeshed`, `extra-paths`, `root`
- **`[src]`** — `include`, `exclude` (gitignore-style glob patterns), `respect-ignore-files`
- **`[[overrides]]`** — Overrides de reglas por archivo con `include`/`exclude` globs
- **`[terminal]`** — `error-on-warning`, `output-format`

### Arquitectura

- **Escrito en Rust** — Binario nativo de alta performance
- **Incremental fino** — Actualiza solo las partes afectadas del código (latencia en milisegundos)
- **Ambos modelos de diagnóstico** — Pull (`textDocument/diagnostic`) y push (`textDocument/publishDiagnostics`)

## TyServer — Cliente LSP para ty

### Implementación

`ty_server.py` contiene la clase `TyServer` que maneja toda la comunicación con `ty server` via subprocess:

- **Transporte:** stdio (stdin/stdout) con framing LSP (`Content-Length`)
- **Protocolo:** JSON-RPC 2.0
- **Métodos clave:**
  - `start()` — lanza `ty server` como subprocess
  - `send_request(method, params)` — envía request, retorna ID
  - `send_notification(method, params)` — envía notificación (sin respuesta)
  - `send_and_wait(method, params)` — envía request y lee hasta obtener la respuesta con el ID correcto (descarta notificaciones entremedio)
  - `read_message()` — lee un mensaje con framing `Content-Length`
  - `stop()` — termina el subprocess

### Flujo LSP: didOpen → hover

Para hacer hover sobre un archivo, primero hay que notificar a ty que el archivo está "abierto". El flujo completo es:

#### 1. Initialize (request)

```python
resp = await server.send_and_wait("initialize", {
    "processId": None,
    "rootUri": root_uri,  # file:///C:/path/to/project
    "capabilities": {},
})
# resp["result"]["serverInfo"] → {"name": "ty", "version": "0.0.33 ..."}
# resp["result"]["capabilities"] → capabilities del servidor
```

#### 2. Initialized (notificación — obligatoria)

```python
await server.send_notification("initialized", {})
```

#### 3. textDocument/didOpen (notificación)

```python
import json
from pathlib import Path

file_path = Path("sample.py").resolve()
file_uri = file_path.as_uri()  # file:///C:/Users/.../sample.py
content = file_path.read_text(encoding="utf-8")

await server.send_notification("textDocument/didOpen", {
    "textDocument": {
        "uri": file_uri,
        "languageId": "python",
        "version": 1,
        "text": content,
    }
})
```

- **`uri`** — URI del archivo (usar `Path.as_uri()`)
- **`languageId`** — siempre `"python"` para ty
- **`version`** — número de versión del documento (incrementar si se modifica)
- **`text`** — contenido completo del archivo

#### 4. textDocument/hover (request)

```python
resp = await server.send_and_wait("textDocument/hover", {
    "textDocument": {"uri": file_uri},
    "position": {"line": 3, "character": 4},  # 0-indexed
})
```

**Parámetros:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `textDocument.uri` | `string` | URI del archivo abierto con didOpen |
| `position.line` | `int` | Línea (0-indexed) |
| `position.character` | `int` | Columna (0-indexed, UTF-16) |

**Respuesta exitosa:**

```json
{
  "contents": {
    "kind": "plaintext",
    "value": "def greet(name: str) -> str"
  },
  "range": {
    "start": {"line": 3, "character": 4},
    "end": {"line": 3, "character": 9}
  }
}
```

- **`contents.value`** — tipo inferido, firma de función, o documentación
- **`contents.kind`** — `"plaintext"` o `"markdown"`
- **`range`** — rango del símbolo bajo el cursor (opcional)
- Si no hay info, `contents` puede ser `null` o string vacío

#### Notas importantes

- ty envía `textDocument/publishDiagnostics` como notificación push después de didOpen. `send_and_wait` las descarta automáticamente.
- Las posiciones son 0-indexed (línea 3 = 4ta línea, carácter 4 = 5to carácter).
- Un archivo debe estar "abierto" (didOpen) antes de hacer hover sobre él.
- Para actualizar contenido: enviar `textDocument/didChange` o hacer didOpen con nueva versión.

## FastMCP — Framework para servidores MCP

### Creación del servidor

```python
from fastmcp import FastMCP

mcp = FastMCP(
    name="mi-servidor",         # Nombre del servidor (requerido si no se usa generate_name)
    instructions="Descripción", # Instrucciones para el cliente
    version="1.0.0",            # Versión del servidor
    lifespan=my_lifespan,       # Función lifespan (startup/shutdown)
    tools=[func1, func2],       # Tools pre-registradas
    on_duplicate="warn",        # Comportamiento ante duplicados: "warn"|"error"|"replace"|"ignore"
    mask_error_details=False,   # Enmascarar detalles de errores
    strict_input_validation=False,  # Validación estricta de inputs
    session_state_store=None,   # Store personalizado para estado de sesión (default: MemoryStore)
)
```

### Lifespan (Stateful — Startup/Shutdown)

El lifespan permite ejecutar código al inicio y al final del ciclo de vida del servidor. Es la forma de hacer un servidor **stateful**: iniciar procesos, abrir conexiones, etc.

**Lifespan simple:**

```python
from contextlib import asynccontextmanager
from fastmcp import FastMCP

@asynccontextmanager
async def my_lifespan(server: FastMCP):
    # Startup — se ejecuta al iniciar el servidor
    process = await start_external_process()
    yield {"process": process}  # Este dict queda accesible vía ctx.lifespan_context
    # Shutdown — se ejecuta al detener el servidor
    await process.terminate()

mcp = FastMCP("server", lifespan=my_lifespan)
```

**Lifespan composable (combinar múltiples con `|`):**

```python
from fastmcp.server.lifespan import lifespan

@lifespan
async def db_lifespan(server):
    conn = await connect_db()
    yield {"db": conn}
    await conn.close()

@lifespan
async def cache_lifespan(server):
    cache = await connect_cache()
    yield {"cache": cache}
    await cache.close()

# Se combinan con el operador | (izquierda entra primero, sale último)
mcp = FastMCP("server", lifespan=db_lifespan | cache_lifespan)
```

**Acceder al contexto del lifespan desde una tool:**

```python
@mcp.tool
async def my_tool(ctx: Context) -> str:
    process = ctx.lifespan_context.get("process")
    return str(process)
```

### Tools

Las tools son funciones que el cliente MCP puede invocar. Se registran con el decorator `@mcp.tool`.

```python
from fastmcp import FastMCP, Context

mcp = FastMCP("server")

# Tool simple
@mcp.tool
def add(a: int, b: int) -> int:
    return a + b

# Tool con nombre personalizado y descripción
@mcp.tool(name="suma", description="Suma dos números")
def add(a: int, b: int) -> int:
    return a + b

# Tool async con Context (para logging, progreso, estado)
@mcp.tool
async def process_data(data: str, ctx: Context) -> str:
    await ctx.info(f"Procesando: {data}")
    await ctx.report_progress(50, 100, "Procesando")
    return f"Procesado: {data}"

# Patrones de uso del decorator:
# @mcp.tool                    — sin paréntesis
# @mcp.tool()                  — paréntesis vacíos
# @mcp.tool("custom_name")     — nombre como primer argumento
# @mcp.tool(name="custom")     — nombre como keyword
# mcp.tool(func, name="custom") — llamada directa
```

**Parámetros del decorator `@mcp.tool`:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | `str \| None` | Nombre de la tool |
| `description` | `str \| None` | Descripción |
| `tags` | `set[str] \| None` | Tags de categorización |
| `output_schema` | `dict \| None` | JSON schema del output |
| `annotations` | `ToolAnnotations \| None` | Anotaciones de comportamiento |
| `timeout` | `float \| None` | Timeout en segundos |
| `task` | `bool \| TaskConfig \| None` | Soporte como background task |

### Resources

Los resources exponen datos que el cliente puede leer. Se registran con `@mcp.resource`.

```python
@mcp.resource("resource://config")
def get_config() -> str:
    return '{"key": "value"}'

# Resource template con parámetros en la URI
@mcp.resource("resource://user/{user_id}")
def get_user(user_id: str) -> str:
    return f'User data for {user_id}'

# Resource con Context
@mcp.resource("resource://data")
async def get_data(ctx: Context) -> str:
    await ctx.info("Leyendo resource")
    return "data"
```

**Parámetros del decorator `@mcp.resource`:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `uri` | `str` | URI del resource (requerido) |
| `name` | `str \| None` | Nombre |
| `description` | `str \| None` | Descripción |
| `mime_type` | `str \| None` | MIME type del contenido |
| `tags` | `set[str] \| None` | Tags |

### Prompts

Los prompts son plantillas de mensajes que el cliente puede usar. Se registran con `@mcp.prompt`.

```python
@mcp.prompt
def review_code(code: str) -> str:
    return f"Please review this code:\n{code}"

@mcp.prompt(name="explain", description="Explica código")
def explain_code(code: str) -> str:
    return f"Explain this code:\n{code}"
```

### Context (`Context`)

El objeto `Context` se inyecta automáticamente cuando un parámetro está anotado con `Context`.

```python
from fastmcp import Context

@mcp.tool
async def my_tool(x: int, ctx: Context) -> str:
    # Logging al cliente
    await ctx.debug("debug message")
    await ctx.info("info message")
    await ctx.warning("warning message")
    await ctx.error("error message")

    # Reportar progreso
    await ctx.report_progress(50, 100, "Procesando")

    # Leer resources
    data = await ctx.read_resource("resource://data")

    # Estado de sesión (persiste entre requests de la misma sesión)
    await ctx.set_state("key", "value")          # Serializable (JSON)
    await ctx.set_state("client", obj, serializable=False)  # No serializable (solo request actual)
    value = await ctx.get_state("key")
    await ctx.delete_state("key")

    # Acceder al lifespan context
    process = ctx.lifespan_context.get("process")

    # Info de la request
    request_id = ctx.request_id
    session_id = ctx.session_id
    client_id = ctx.client_id
    transport = ctx.transport  # "stdio" | "sse" | "streamable-http"

    return str(x)
```

### Transportes y ejecución del servidor

**Ejecución síncrona (bloqueante):**

```python
mcp.run()                          # Usa el transporte de settings (default: "stdio")
mcp.run(transport="stdio")         # stdio
mcp.run(transport="http")          # HTTP en 127.0.0.1:8000
mcp.run(transport="sse")           # SSE
mcp.run(transport="streamable-http")  # Streamable HTTP
```

**Ejecución asíncrona:**

```python
await mcp.run_async(transport="stdio")
await mcp.run_stdio_async()
await mcp.run_http_async(transport="http", host="0.0.0.0", port=8080)
await mcp.run_http_async(transport="sse")
await mcp.run_http_async(transport="streamable-http")
```

**Transportes disponibles:**

| Transporte | Descripción |
|---|---|
| `stdio` | Comunicación por stdin/stdout (default). Ideal para integración con editores |
| `http` / `streamable-http` | HTTP con Streamable HTTP (POST en `/mcp`). Usa Uvicorn + Starlette |
| `sse` | Server-Sent Events. Legado, usar `streamable-http` en su lugar |

**Configuración de transporte vía settings (env vars):**

| Env Var | Default | Descripción |
|---|---|---|
| `FASTMCP_TRANSPORT` | `stdio` | Transporte por defecto |
| `FASTMCP_HOST` | `127.0.0.1` | Host para HTTP |
| `FASTMCP_PORT` | `8000` | Puerto para HTTP |
| `FASTMCP_STREAMABLE_HTTP_PATH` | `/mcp` | Path endpoint Streamable HTTP |
| `FASTMCP_SSE_PATH` | `/sse` | Path endpoint SSE |
| `FASTMCP_STATELESS_HTTP` | `false` | Modo stateless (sin sesión) |

### Middleware

Los middleware permiten interceptar requests/response del protocolo MCP.

```python
from fastmcp.server.middleware import Middleware, MiddlewareContext

class MyMiddleware(Middleware):
    async def on_request(self, context: MiddlewareContext, call_next):
        # Pre-procesamiento
        result = await call_next(context)
        # Post-procesamiento
        return result

mcp.add_middleware(MyMiddleware())
```

### Rutas HTTP personalizadas

```python
from starlette.requests import Request
from starlette.responses import JSONResponse

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})
```

### Providers y Mounting

Los providers permiten montar servidores MCP dentro de otros, con namespacing:

```python
# Montar un servidor dentro de otro
mcp.mount(child_server, namespace="api")
# Las tools del child se vuelven "api_toolname"
```

### Arquitectura interna

- **`FastMCP`** hereda de `AggregateProvider`, `LifespanMixin`, `MCPOperationsMixin`, `TransportMixin`
- **`LocalProvider`** almacena tools/resources/prompts registrados localmente
- **`AggregateProvider`** agrega múltiples providers con namespacing
- **`Context`** usa `ContextVar` para inyección de dependencias
- **State store** usa `key_value.aio` con `MemoryStore` por defecto (session-scoped, TTL 24h)
- **HTTP** usa Starlette + Uvicorn; **stdio** usa el MCP SDK directamente
- **Lifespan** soporta composición con operador `|` para combinar múltiples contextos

## Project Context (Auto-generated)

> **Nota**: Esta sección se genera automáticamente antes de cada query.
> No la edites manualmente ya que se sobrescribirá.
>
> Providers activos: generate_system_context, generate_extended_system_context, generate_filetree_context, generate_stats_context, generate_git_context, generate_git_status_context

### System Info

- **OS**: 🪟 Windows 11 (AMD64)
- **User**: `user@DESKTOP-92K2Q7P`
- **Home**: `C:\Users\user`
- **Shell**: `C:\WINDOWS\system32\cmd.exe`
- **Python**: `3.14.2` → `C:\Python314\python.exe`
- **Date/Time**: 2026-04-29 19:46:32 (SA Pacific Standard Time)
- **Unix Timestamp**: `1777509992`



### Extended System Info

- **LANG**: `unknown`
- **TERM**: `unknown`
- **PATH**:
  ```
  C:\Python314\Scripts\;C:\Python314\;C:\WINDOWS\system32;C:\WINDOWS;C:\WINDOWS\System32\Wbem;
  ... C:\Users\user\AppData\Roaming\Python\Python314\Scripts;C:\Users\user\AppData\Local\Programs\Microsoft VS Code\bin;C:\Users\user\.lmstudio\bin
  ```



### File Tree

```
python-code/
├── .github/
│   └── workflows/
│       └── publish.yml
├── src/
│   └── ty_lsp/
│       ├── __init__.py
│       ├── lsp.py
│       └── server.py
├── .gitignore
├── CLAUDE.md
├── pyproject.toml
├── sample.py
├── test_flow.py
├── ty_client.py
└── ty_server.py
```

### Project Stats

- **Python files**: 7
- **JS/TS files**: 0
- **Total tracked files**: 7

### Git Info

- **Branch**: `master`

### Git Status

```
  ?? .github/
  ?? .gitignore
  ?? CLAUDE.md
  ?? pyproject.toml
  ?? sample.py
  ?? src/
  ?? test_flow.py
  ?? ty_client.py
  ?? ty_server.py
```

---