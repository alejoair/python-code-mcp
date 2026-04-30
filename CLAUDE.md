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

## Arquitectura del paquete `ty_lsp`

El proyecto expone un único entry point `python-code-mcp` con dos modos de operación:

```
python-code-mcp            → lanza el servidor MCP (stdio)
python-code-mcp install    → registra el servidor en Claude Code y sale
```

### Módulos

| Archivo | Clase/Función | Descripción |
|---|---|---|
| `src/ty_lsp/server.py` | `mcp`, `main()` | Servidor FastMCP + entry point (intercepta `install` por CLI) |
| `src/ty_lsp/lsp.py` | `TyServer` | Cliente LSP para ty (subprocess, JSON-RPC 2.0, framing Content-Length) |
| `src/ty_lsp/install.py` | `run_install()` | Lógica de instalación (`claude mcp add`) |

### Entry point (`pyproject.toml`)

```toml
[project.scripts]
python-code-mcp = "ty_lsp.server:main"
```

Un solo entry point. `main()` revisa `sys.argv[1]` para decidir si instala o arranca el servidor.

### Flujo: `server.py` → `lsp.py`

1. `main()` → `mcp.run(transport="stdio")` arranca FastMCP
2. El lifespan `ty_lifespan` crea un `TyServer`, lo inicia y lo inicializa
3. Las tools (ej: `hover`) acceden al `TyServer` vía `ctx.lifespan_context["ty"]`
4. `TyServer` maneja toda la comunicación LSP con ty via subprocess (stdin/stdout)

## TyServer — Cliente LSP para ty

### Implementación

`src/ty_lsp/lsp.py` contiene la clase `TyServer` que maneja toda la comunicación con `ty server` via subprocess:

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
- **Date/Time**: 2026-04-29 21:35:48 (SA Pacific Standard Time)
- **Unix Timestamp**: `1777516548`



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
├── Python314Libsite-packages/
│   ├── _yaml/
│   │   └── __init__.py
│   ├── adodbapi/
│   │   ├── examples/
│   │   │   ├── db_print.py
│   │   │   ├── db_table_names.py
│   │   │   ├── xls_read.py
│   │   │   └── xls_write.py
│   │   ├── test/
│   │   │   ├── adodbapitest.py
│   │   │   ├── adodbapitestconfig.py
│   │   │   ├── dbapi20.py
│   │   │   ├── is64bit.py
│   │   │   ├── setuptestframework.py
│   │   │   ├── test_adodbapi_dbapi20.py
│   │   │   └── tryconnection.py
│   │   ├── __init__.py
│   │   ├── ado_consts.py
│   │   ├── adodbapi.py
│   │   ├── apibase.py
│   │   ├── is64bit.py
│   │   ├── license.txt
│   │   ├── process_connect_string.py
│   │   ├── readme.txt
│   │   ├── schema_table.py
│   │   └── setup.py
│   ├── aiofile/
│   │   ├── __init__.py
│   │   ├── aio.py
│   │   ├── py.typed
│   │   ├── utils.py
│   │   └── version.py
│   ├── aiofile-3.9.0.dist-info/
│   │   ├── INSTALLER
│   │   ├── LICENCE
│   │   ├── LICENCE.md
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── annotated_types/
│   │   ├── __init__.py
│   │   ├── py.typed
│   │   └── test_cases.py
│   ├── annotated_types-0.7.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── anyio/
│   │   ├── _backends/
│   │   │   ├── __init__.py
│   │   │   ├── _asyncio.py
│   │   │   └── _trio.py
│   │   ├── _core/
│   │   │   ├── __init__.py
│   │   │   ├── _asyncio_selector_thread.py
│   │   │   ├── _contextmanagers.py
│   │   │   ├── _eventloop.py
│   │   │   ├── _exceptions.py
│   │   │   ├── _fileio.py
│   │   │   ├── _resources.py
│   │   │   ├── _signals.py
│   │   │   ├── _sockets.py
│   │   │   ├── _streams.py
│   │   │   ├── _subprocesses.py
│   │   │   ├── _synchronization.py
│   │   │   ├── _tasks.py
│   │   │   ├── _tempfile.py
│   │   │   ├── _testing.py
│   │   │   └── _typedattr.py
│   │   ├── abc/
│   │   │   ├── __init__.py
│   │   │   ├── _eventloop.py
│   │   │   ├── _resources.py
│   │   │   ├── _sockets.py
│   │   │   ├── _streams.py
│   │   │   ├── _subprocesses.py
│   │   │   ├── _tasks.py
│   │   │   └── _testing.py
│   │   ├── streams/
│   │   │   ├── __init__.py
│   │   │   ├── buffered.py
│   │   │   ├── file.py
│   │   │   ├── memory.py
│   │   │   ├── stapled.py
│   │   │   ├── text.py
│   │   │   └── tls.py
│   │   ├── __init__.py
│   │   ├── from_thread.py
│   │   ├── functools.py
│   │   ├── lowlevel.py
│   │   ├── py.typed
│   │   ├── pytest_plugin.py
│   │   ├── to_interpreter.py
│   │   ├── to_process.py
│   │   └── to_thread.py
│   ├── anyio-4.13.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── attr/
│   │   ├── __init__.py
│   │   ├── __init__.pyi
│   │   ├── _cmp.py
│   │   ├── _cmp.pyi
│   │   ├── _compat.py
│   │   ├── _config.py
│   │   ├── _funcs.py
│   │   ├── _make.py
│   │   ├── _next_gen.py
│   │   ├── _typing_compat.pyi
│   │   ├── _version_info.py
│   │   ├── _version_info.pyi
│   │   ├── converters.py
│   │   ├── converters.pyi
│   │   ├── exceptions.py
│   │   ├── exceptions.pyi
│   │   ├── filters.py
│   │   ├── filters.pyi
│   │   ├── py.typed
│   │   ├── setters.py
│   │   ├── setters.pyi
│   │   ├── validators.py
│   │   └── validators.pyi
│   ├── attrs/
│   │   ├── __init__.py
│   │   ├── __init__.pyi
│   │   ├── converters.py
│   │   ├── exceptions.py
│   │   ├── filters.py
│   │   ├── py.typed
│   │   ├── setters.py
│   │   └── validators.py
│   ├── attrs-26.1.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── authlib/
│   │   ├── common/
│   │   │   ├── __init__.py
│   │   │   ├── encoding.py
│   │   │   ├── errors.py
│   │   │   ├── security.py
│   │   │   └── urls.py
│   │   ├── integrations/
│   │   │   ├── base_client/
│   │   │   ├── django_client/
│   │   │   ├── django_oauth1/
│   │   │   ├── django_oauth2/
│   │   │   ├── flask_client/
│   │   │   ├── flask_oauth1/
│   │   │   ├── flask_oauth2/
│   │   │   ├── httpx_client/
│   │   │   ├── requests_client/
│   │   │   ├── sqla_oauth2/
│   │   │   ├── starlette_client/
│   │   │   └── __init__.py
│   │   ├── jose/
│   │   │   ├── drafts/
│   │   │   ├── rfc7515/
│   │   │   ├── rfc7516/
│   │   │   ├── rfc7517/
│   │   │   ├── rfc7518/
│   │   │   ├── rfc7519/
│   │   │   ├── rfc8037/
│   │   │   ├── __init__.py
│   │   │   ├── errors.py
│   │   │   ├── jwk.py
│   │   │   └── util.py
│   │   ├── oauth1/
│   │   │   ├── rfc5849/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   └── errors.py
│   │   ├── oauth2/
│   │   │   ├── rfc6749/
│   │   │   ├── rfc6750/
│   │   │   ├── rfc7009/
│   │   │   ├── rfc7521/
│   │   │   ├── rfc7523/
│   │   │   ├── rfc7591/
│   │   │   ├── rfc7592/
│   │   │   ├── rfc7636/
│   │   │   ├── rfc7662/
│   │   │   ├── rfc8414/
│   │   │   ├── rfc8628/
│   │   │   ├── rfc8693/
│   │   │   ├── rfc9068/
│   │   │   ├── rfc9101/
│   │   │   ├── rfc9207/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── base.py
│   │   │   ├── claims.py
│   │   │   └── client.py
│   │   ├── oidc/
│   │   │   ├── core/
│   │   │   ├── discovery/
│   │   │   ├── registration/
│   │   │   ├── rpinitiated/
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── _joserfc_helpers.py
│   │   ├── consts.py
│   │   └── deprecate.py
│   ├── authlib-1.7.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── beartype/
│   │   ├── _cave/
│   │   │   ├── __init__.py
│   │   │   ├── _caveabc.py
│   │   │   ├── _cavefast.py
│   │   │   └── _cavemap.py
│   │   ├── _check/
│   │   │   ├── code/
│   │   │   ├── convert/
│   │   │   ├── error/
│   │   │   ├── forward/
│   │   │   ├── logic/
│   │   │   ├── metadata/
│   │   │   ├── pep/
│   │   │   ├── signature/
│   │   │   ├── __init__.py
│   │   │   ├── _checksnip.py
│   │   │   └── checkmake.py
│   │   ├── _conf/
│   │   │   ├── decorplace/
│   │   │   ├── __init__.py
│   │   │   ├── _confget.py
│   │   │   ├── _confoverrides.py
│   │   │   ├── confcommon.py
│   │   │   ├── confenum.py
│   │   │   ├── confmain.py
│   │   │   └── conftest.py
│   │   ├── _data/
│   │   │   ├── api/
│   │   │   ├── claw/
│   │   │   ├── cls/
│   │   │   ├── code/
│   │   │   ├── conf/
│   │   │   ├── error/
│   │   │   ├── func/
│   │   │   ├── hint/
│   │   │   ├── kind/
│   │   │   ├── os/
│   │   │   ├── typing/
│   │   │   └── __init__.py
│   │   ├── _decor/
│   │   │   ├── _nontype/
│   │   │   ├── _type/
│   │   │   ├── __init__.py
│   │   │   ├── decorcache.py
│   │   │   ├── decorcore.py
│   │   │   └── decormain.py
│   │   ├── _util/
│   │   │   ├── api/
│   │   │   ├── ast/
│   │   │   ├── bear/
│   │   │   ├── cache/
│   │   │   ├── cls/
│   │   │   ├── error/
│   │   │   ├── func/
│   │   │   ├── hint/
│   │   │   ├── kind/
│   │   │   ├── module/
│   │   │   ├── os/
│   │   │   ├── path/
│   │   │   ├── py/
│   │   │   ├── text/
│   │   │   ├── __init__.py
│   │   │   ├── utilobjattr.py
│   │   │   ├── utilobject.py
│   │   │   └── utilobjmake.py
│   │   ├── bite/
│   │   │   ├── collection/
│   │   │   ├── kind/
│   │   │   ├── __init__.py
│   │   │   └── _infermain.py
│   │   ├── cave/
│   │   │   ├── __init__.py
│   │   │   └── _cavelib.py
│   │   ├── claw/
│   │   │   ├── _ast/
│   │   │   ├── _importlib/
│   │   │   ├── _package/
│   │   │   ├── __init__.py
│   │   │   ├── _clawmain.py
│   │   │   └── _clawstate.py
│   │   ├── door/
│   │   │   ├── _cls/
│   │   │   ├── _func/
│   │   │   └── __init__.py
│   │   ├── peps/
│   │   │   ├── __init__.py
│   │   │   └── _pep563.py
│   │   ├── plug/
│   │   │   ├── __init__.py
│   │   │   └── _plughintable.py
│   │   ├── roar/
│   │   │   ├── __init__.py
│   │   │   ├── _roarexc.py
│   │   │   └── _roarwarn.py
│   │   ├── typing/
│   │   │   ├── __init__.py
│   │   │   ├── _typingcache.py
│   │   │   └── _typingpep544.py
│   │   ├── vale/
│   │   │   ├── _core/
│   │   │   ├── _is/
│   │   │   ├── _util/
│   │   │   └── __init__.py
│   │   ├── __init__.py
│   │   ├── meta.py
│   │   └── py.typed
│   ├── beartype-0.22.9.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── cachetools/
│   │   ├── __init__.py
│   │   ├── _cached.py
│   │   ├── _cachedmethod.py
│   │   ├── func.py
│   │   └── keys.py
│   ├── cachetools-7.0.6.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── caio/
│   │   ├── src/
│   │   │   └── threadpool/
│   │   ├── __init__.py
│   │   ├── abstract.py
│   │   ├── asyncio_base.py
│   │   ├── linux_aio.pyi
│   │   ├── linux_aio_asyncio.py
│   │   ├── py.typed
│   │   ├── python_aio.py
│   │   ├── python_aio_asyncio.py
│   │   ├── thread_aio.pyi
│   │   ├── thread_aio_asyncio.py
│   │   └── version.py
│   ├── caio-0.9.25.dist-info/
│   │   ├── licenses/
│   │   │   └── COPYING
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── certifi/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cacert.pem
│   │   ├── core.py
│   │   └── py.typed
│   ├── certifi-2026.4.22.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── cffi/
│   │   ├── __init__.py
│   │   ├── _cffi_errors.h
│   │   ├── _cffi_include.h
│   │   ├── _embedding.h
│   │   ├── _imp_emulation.py
│   │   ├── _shimmed_dist_utils.py
│   │   ├── api.py
│   │   ├── backend_ctypes.py
│   │   ├── cffi_opcode.py
│   │   ├── commontypes.py
│   │   ├── cparser.py
│   │   ├── error.py
│   │   ├── ffiplatform.py
│   │   ├── lock.py
│   │   ├── model.py
│   │   ├── parse_c_type.h
│   │   ├── pkgconfig.py
│   │   ├── recompiler.py
│   │   ├── setuptools_ext.py
│   │   ├── vengine_cpy.py
│   │   ├── vengine_gen.py
│   │   └── verifier.py
│   ├── cffi-2.0.0.dist-info/
│   │   ├── licenses/
│   │   │   ├── AUTHORS
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── click/
│   │   ├── __init__.py
│   │   ├── _compat.py
│   │   ├── _termui_impl.py
│   │   ├── _textwrap.py
│   │   ├── _utils.py
│   │   ├── _winconsole.py
│   │   ├── core.py
│   │   ├── decorators.py
│   │   ├── exceptions.py
│   │   ├── formatting.py
│   │   ├── globals.py
│   │   ├── parser.py
│   │   ├── py.typed
│   │   ├── shell_completion.py
│   │   ├── termui.py
│   │   ├── testing.py
│   │   ├── types.py
│   │   └── utils.py
│   ├── click-8.3.3.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── colorama/
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── ansi_test.py
│   │   │   ├── ansitowin32_test.py
│   │   │   ├── initialise_test.py
│   │   │   ├── isatty_test.py
│   │   │   ├── utils.py
│   │   │   └── winterm_test.py
│   │   ├── __init__.py
│   │   ├── ansi.py
│   │   ├── ansitowin32.py
│   │   ├── initialise.py
│   │   ├── win32.py
│   │   └── winterm.py
│   ├── colorama-0.4.6.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── cryptography/
│   │   ├── hazmat/
│   │   │   ├── asn1/
│   │   │   ├── backends/
│   │   │   ├── bindings/
│   │   │   ├── decrepit/
│   │   │   ├── primitives/
│   │   │   ├── __init__.py
│   │   │   └── _oid.py
│   │   ├── x509/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── certificate_transparency.py
│   │   │   ├── extensions.py
│   │   │   ├── general_name.py
│   │   │   ├── name.py
│   │   │   ├── ocsp.py
│   │   │   ├── oid.py
│   │   │   └── verification.py
│   │   ├── __about__.py
│   │   ├── __init__.py
│   │   ├── exceptions.py
│   │   ├── fernet.py
│   │   ├── py.typed
│   │   └── utils.py
│   ├── cryptography-47.0.0.dist-info/
│   │   ├── licenses/
│   │   │   ├── LICENSE
│   │   │   ├── LICENSE.APACHE
│   │   │   └── LICENSE.BSD
│   │   ├── sboms/
│   │   │   ├── cryptography-rust.cyclonedx.json
│   │   │   └── sbom.json
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── cyclopts/
│   │   ├── argument/
│   │   │   ├── __init__.py
│   │   │   ├── _argument.py
│   │   │   ├── _collection.py
│   │   │   └── utils.py
│   │   ├── cli/
│   │   │   ├── __init__.py
│   │   │   ├── _complete.py
│   │   │   ├── docs.py
│   │   │   └── run.py
│   │   ├── completion/
│   │   │   ├── __init__.py
│   │   │   ├── _base.py
│   │   │   ├── bash.py
│   │   │   ├── detect.py
│   │   │   ├── fish.py
│   │   │   ├── install.py
│   │   │   └── zsh.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── _common.py
│   │   │   ├── _env.py
│   │   │   ├── _json.py
│   │   │   ├── _toml.py
│   │   │   └── _yaml.py
│   │   ├── docs/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── html.py
│   │   │   ├── markdown.py
│   │   │   ├── rst.py
│   │   │   └── types.py
│   │   ├── ext/
│   │   │   ├── __init__.py
│   │   │   ├── mkdocs.py
│   │   │   └── sphinx.py
│   │   ├── help/
│   │   │   ├── formatters/
│   │   │   ├── __init__.py
│   │   │   ├── help.py
│   │   │   ├── inline_text.py
│   │   │   ├── protocols.py
│   │   │   ├── rst_preprocessor.py
│   │   │   ├── silent.py
│   │   │   └── specs.py
│   │   ├── validators/
│   │   │   ├── __init__.py
│   │   │   ├── _group.py
│   │   │   ├── _number.py
│   │   │   └── _path.py
│   │   ├── __init__.py
│   │   ├── __init__.pyi
│   │   ├── __main__.py
│   │   ├── _convert.py
│   │   ├── _edit.py
│   │   ├── _env_var.py
│   │   ├── _markup.py
│   │   ├── _path_type.py
│   │   ├── _result_action.py
│   │   ├── _run.py
│   │   ├── _version.py
│   │   ├── annotations.py
│   │   ├── app_stack.py
│   │   ├── bind.py
│   │   ├── command_spec.py
│   │   ├── core.py
│   │   ├── exceptions.py
│   │   ├── field_info.py
│   │   ├── group.py
│   │   ├── group_extractors.py
│   │   ├── loader.py
│   │   ├── panel.py
│   │   ├── parameter.py
│   │   ├── protocols.py
│   │   ├── py.typed
│   │   ├── sphinx_ext.py
│   │   ├── token.py
│   │   ├── types.py
│   │   └── utils.py
│   ├── cyclopts-4.11.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── dns/
│   │   ├── dnssecalgs/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── cryptography.py
│   │   │   ├── dsa.py
│   │   │   ├── ecdsa.py
│   │   │   ├── eddsa.py
│   │   │   └── rsa.py
│   │   ├── quic/
│   │   │   ├── __init__.py
│   │   │   ├── _asyncio.py
│   │   │   ├── _common.py
│   │   │   ├── _sync.py
│   │   │   └── _trio.py
│   │   ├── rdtypes/
│   │   │   ├── ANY/
│   │   │   ├── CH/
│   │   │   ├── IN/
│   │   │   ├── __init__.py
│   │   │   ├── dnskeybase.py
│   │   │   ├── dsbase.py
│   │   │   ├── euibase.py
│   │   │   ├── mxbase.py
│   │   │   ├── nsbase.py
│   │   │   ├── svcbbase.py
│   │   │   ├── tlsabase.py
│   │   │   ├── txtbase.py
│   │   │   └── util.py
│   │   ├── __init__.py
│   │   ├── _asyncbackend.py
│   │   ├── _asyncio_backend.py
│   │   ├── _ddr.py
│   │   ├── _features.py
│   │   ├── _immutable_ctx.py
│   │   ├── _no_ssl.py
│   │   ├── _tls_util.py
│   │   ├── _trio_backend.py
│   │   ├── asyncbackend.py
│   │   ├── asyncquery.py
│   │   ├── asyncresolver.py
│   │   ├── btree.py
│   │   ├── btreezone.py
│   │   ├── dnssec.py
│   │   ├── dnssectypes.py
│   │   ├── e164.py
│   │   ├── edns.py
│   │   ├── entropy.py
│   │   ├── enum.py
│   │   ├── exception.py
│   │   ├── flags.py
│   │   ├── grange.py
│   │   ├── immutable.py
│   │   ├── inet.py
│   │   ├── ipv4.py
│   │   ├── ipv6.py
│   │   ├── message.py
│   │   ├── name.py
│   │   ├── namedict.py
│   │   ├── nameserver.py
│   │   ├── node.py
│   │   ├── opcode.py
│   │   ├── py.typed
│   │   ├── query.py
│   │   ├── rcode.py
│   │   ├── rdata.py
│   │   ├── rdataclass.py
│   │   ├── rdataset.py
│   │   ├── rdatatype.py
│   │   ├── renderer.py
│   │   ├── resolver.py
│   │   ├── reversename.py
│   │   ├── rrset.py
│   │   ├── serial.py
│   │   ├── set.py
│   │   ├── tokenizer.py
│   │   ├── transaction.py
│   │   ├── tsig.py
│   │   ├── tsigkeyring.py
│   │   ├── ttl.py
│   │   ├── update.py
│   │   ├── version.py
│   │   ├── versioned.py
│   │   ├── win32util.py
│   │   ├── wire.py
│   │   ├── xfr.py
│   │   ├── zone.py
│   │   ├── zonefile.py
│   │   └── zonetypes.py
│   ├── dnspython-2.8.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── docstring_parser/
│   │   ├── __init__.py
│   │   ├── attrdoc.py
│   │   ├── common.py
│   │   ├── epydoc.py
│   │   ├── google.py
│   │   ├── numpydoc.py
│   │   ├── parser.py
│   │   ├── py.typed
│   │   ├── rest.py
│   │   └── util.py
│   ├── docstring_parser-0.18.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── docutils/
│   │   ├── languages/
│   │   │   ├── __init__.py
│   │   │   ├── af.py
│   │   │   ├── ar.py
│   │   │   ├── ca.py
│   │   │   ├── cs.py
│   │   │   ├── da.py
│   │   │   ├── de.py
│   │   │   ├── en.py
│   │   │   ├── eo.py
│   │   │   ├── es.py
│   │   │   ├── fa.py
│   │   │   ├── fi.py
│   │   │   ├── fr.py
│   │   │   ├── gl.py
│   │   │   ├── he.py
│   │   │   ├── it.py
│   │   │   ├── ja.py
│   │   │   ├── ka.py
│   │   │   ├── ko.py
│   │   │   ├── lt.py
│   │   │   ├── lv.py
│   │   │   ├── nl.py
│   │   │   ├── pl.py
│   │   │   ├── pt_br.py
│   │   │   ├── ru.py
│   │   │   ├── sk.py
│   │   │   ├── sv.py
│   │   │   ├── uk.py
│   │   │   ├── zh_cn.py
│   │   │   └── zh_tw.py
│   │   ├── parsers/
│   │   │   ├── rst/
│   │   │   ├── __init__.py
│   │   │   ├── commonmark_wrapper.py
│   │   │   ├── docutils_xml.py
│   │   │   ├── null.py
│   │   │   └── recommonmark_wrapper.py
│   │   ├── readers/
│   │   │   ├── __init__.py
│   │   │   ├── doctree.py
│   │   │   ├── pep.py
│   │   │   └── standalone.py
│   │   ├── transforms/
│   │   │   ├── __init__.py
│   │   │   ├── components.py
│   │   │   ├── frontmatter.py
│   │   │   ├── misc.py
│   │   │   ├── parts.py
│   │   │   ├── peps.py
│   │   │   ├── references.py
│   │   │   ├── universal.py
│   │   │   └── writer_aux.py
│   │   ├── utils/
│   │   │   ├── math/
│   │   │   ├── __init__.py
│   │   │   ├── _roman_numerals.py
│   │   │   ├── _typing.py
│   │   │   ├── code_analyzer.py
│   │   │   ├── punctuation_chars.py
│   │   │   ├── smartquotes.py
│   │   │   └── urischemes.py
│   │   ├── writers/
│   │   │   ├── html4css1/
│   │   │   ├── html5_polyglot/
│   │   │   ├── latex2e/
│   │   │   ├── odf_odt/
│   │   │   ├── pep_html/
│   │   │   ├── s5_html/
│   │   │   ├── xetex/
│   │   │   ├── __init__.py
│   │   │   ├── _html_base.py
│   │   │   ├── docutils_xml.py
│   │   │   ├── manpage.py
│   │   │   ├── null.py
│   │   │   └── pseudoxml.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── core.py
│   │   ├── docutils.conf
│   │   ├── examples.py
│   │   ├── frontend.py
│   │   ├── io.py
│   │   ├── nodes.py
│   │   └── statemachine.py
│   ├── docutils-0.22.4.dist-info/
│   │   ├── licenses/
│   │   │   ├── licenses/
│   │   │   └── COPYING.rst
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── dotenv/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cli.py
│   │   ├── ipython.py
│   │   ├── main.py
│   │   ├── parser.py
│   │   ├── py.typed
│   │   ├── variables.py
│   │   └── version.py
│   ├── email_validator/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── deliverability.py
│   │   ├── exceptions.py
│   │   ├── py.typed
│   │   ├── rfc_constants.py
│   │   ├── syntax.py
│   │   ├── types.py
│   │   ├── validate_email.py
│   │   └── version.py
│   ├── email_validator-2.3.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── exceptiongroup/
│   │   ├── __init__.py
│   │   ├── _catch.py
│   │   ├── _exceptions.py
│   │   ├── _formatting.py
│   │   ├── _suppress.py
│   │   ├── _version.py
│   │   └── py.typed
│   ├── exceptiongroup-1.3.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── fastmcp/
│   │   ├── apps/
│   │   │   ├── __init__.py
│   │   │   ├── app.py
│   │   │   ├── approval.py
│   │   │   ├── choice.py
│   │   │   ├── config.py
│   │   │   ├── file_upload.py
│   │   │   ├── form.py
│   │   │   └── generative.py
│   │   ├── cli/
│   │   │   ├── install/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py
│   │   │   ├── apps_dev.py
│   │   │   ├── auth.py
│   │   │   ├── cimd.py
│   │   │   ├── cli.py
│   │   │   ├── client.py
│   │   │   ├── discovery.py
│   │   │   ├── generate.py
│   │   │   ├── run.py
│   │   │   └── tasks.py
│   │   ├── client/
│   │   │   ├── auth/
│   │   │   ├── mixins/
│   │   │   ├── sampling/
│   │   │   ├── transports/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── elicitation.py
│   │   │   ├── logging.py
│   │   │   ├── messages.py
│   │   │   ├── oauth_callback.py
│   │   │   ├── progress.py
│   │   │   ├── roots.py
│   │   │   ├── tasks.py
│   │   │   └── telemetry.py
│   │   ├── contrib/
│   │   │   ├── bulk_tool_caller/
│   │   │   ├── component_manager/
│   │   │   ├── mcp_mixin/
│   │   │   └── README.md
│   │   ├── experimental/
│   │   │   ├── sampling/
│   │   │   ├── server/
│   │   │   ├── transforms/
│   │   │   ├── utilities/
│   │   │   └── __init__.py
│   │   ├── prompts/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── function_prompt.py
│   │   ├── resources/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── function_resource.py
│   │   │   ├── template.py
│   │   │   └── types.py
│   │   ├── server/
│   │   │   ├── auth/
│   │   │   ├── middleware/
│   │   │   ├── mixins/
│   │   │   ├── openapi/
│   │   │   ├── providers/
│   │   │   ├── sampling/
│   │   │   ├── tasks/
│   │   │   ├── transforms/
│   │   │   ├── __init__.py
│   │   │   ├── app.py
│   │   │   ├── apps.py
│   │   │   ├── context.py
│   │   │   ├── dependencies.py
│   │   │   ├── elicitation.py
│   │   │   ├── event_store.py
│   │   │   ├── http.py
│   │   │   ├── lifespan.py
│   │   │   ├── low_level.py
│   │   │   ├── proxy.py
│   │   │   ├── server.py
│   │   │   └── telemetry.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── function_parsing.py
│   │   │   ├── function_tool.py
│   │   │   └── tool_transform.py
│   │   ├── utilities/
│   │   │   ├── mcp_server_config/
│   │   │   ├── openapi/
│   │   │   ├── __init__.py
│   │   │   ├── async_utils.py
│   │   │   ├── auth.py
│   │   │   ├── cli.py
│   │   │   ├── components.py
│   │   │   ├── docstring_parsing.py
│   │   │   ├── exceptions.py
│   │   │   ├── http.py
│   │   │   ├── inspect.py
│   │   │   ├── json_schema.py
│   │   │   ├── json_schema_type.py
│   │   │   ├── lifespan.py
│   │   │   ├── logging.py
│   │   │   ├── mime.py
│   │   │   ├── pagination.py
│   │   │   ├── skills.py
│   │   │   ├── tests.py
│   │   │   ├── timeout.py
│   │   │   ├── token_cache.py
│   │   │   ├── types.py
│   │   │   ├── ui.py
│   │   │   ├── version_check.py
│   │   │   └── versions.py
│   │   ├── __init__.py
│   │   ├── decorators.py
│   │   ├── dependencies.py
│   │   ├── exceptions.py
│   │   ├── mcp_config.py
│   │   ├── py.typed
│   │   ├── settings.py
│   │   ├── telemetry.py
│   │   └── types.py
│   ├── fastmcp-3.2.4.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── REQUESTED
│   │   └── WHEEL
│   ├── griffe/
│   │   ├── _internal/
│   │   │   ├── agents/
│   │   │   ├── docstrings/
│   │   │   ├── extensions/
│   │   │   ├── __init__.py
│   │   │   ├── c3linear.py
│   │   │   ├── collections.py
│   │   │   ├── debug.py
│   │   │   ├── diff.py
│   │   │   ├── encoders.py
│   │   │   ├── enumerations.py
│   │   │   ├── exceptions.py
│   │   │   ├── expressions.py
│   │   │   ├── finder.py
│   │   │   ├── git.py
│   │   │   ├── importer.py
│   │   │   ├── loader.py
│   │   │   ├── logger.py
│   │   │   ├── merger.py
│   │   │   ├── mixins.py
│   │   │   ├── models.py
│   │   │   ├── stats.py
│   │   │   └── tests.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── py.typed
│   ├── griffelib-2.0.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── h11/
│   │   ├── __init__.py
│   │   ├── _abnf.py
│   │   ├── _connection.py
│   │   ├── _events.py
│   │   ├── _headers.py
│   │   ├── _readers.py
│   │   ├── _receivebuffer.py
│   │   ├── _state.py
│   │   ├── _util.py
│   │   ├── _version.py
│   │   ├── _writers.py
│   │   └── py.typed
│   ├── h11-0.16.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── httpcore/
│   │   ├── _async/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── connection_pool.py
│   │   │   ├── http11.py
│   │   │   ├── http2.py
│   │   │   ├── http_proxy.py
│   │   │   ├── interfaces.py
│   │   │   └── socks_proxy.py
│   │   ├── _backends/
│   │   │   ├── __init__.py
│   │   │   ├── anyio.py
│   │   │   ├── auto.py
│   │   │   ├── base.py
│   │   │   ├── mock.py
│   │   │   ├── sync.py
│   │   │   └── trio.py
│   │   ├── _sync/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── connection_pool.py
│   │   │   ├── http11.py
│   │   │   ├── http2.py
│   │   │   ├── http_proxy.py
│   │   │   ├── interfaces.py
│   │   │   └── socks_proxy.py
│   │   ├── __init__.py
│   │   ├── _api.py
│   │   ├── _exceptions.py
│   │   ├── _models.py
│   │   ├── _ssl.py
│   │   ├── _synchronization.py
│   │   ├── _trace.py
│   │   ├── _utils.py
│   │   └── py.typed
│   ├── httpcore-1.0.9.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── httpx/
│   │   ├── _transports/
│   │   │   ├── __init__.py
│   │   │   ├── asgi.py
│   │   │   ├── base.py
│   │   │   ├── default.py
│   │   │   ├── mock.py
│   │   │   └── wsgi.py
│   │   ├── __init__.py
│   │   ├── __version__.py
│   │   ├── _api.py
│   │   ├── _auth.py
│   │   ├── _client.py
│   │   ├── _config.py
│   │   ├── _content.py
│   │   ├── _decoders.py
│   │   ├── _exceptions.py
│   │   ├── _main.py
│   │   ├── _models.py
│   │   ├── _multipart.py
│   │   ├── _status_codes.py
│   │   ├── _types.py
│   │   ├── _urlparse.py
│   │   ├── _urls.py
│   │   ├── _utils.py
│   │   └── py.typed
│   ├── httpx-0.28.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── httpx_sse/
│   │   ├── __init__.py
│   │   ├── _api.py
│   │   ├── _decoders.py
│   │   ├── _exceptions.py
│   │   ├── _models.py
│   │   └── py.typed
│   ├── httpx_sse-0.4.3.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── idna/
│   │   ├── __init__.py
│   │   ├── codec.py
│   │   ├── compat.py
│   │   ├── core.py
│   │   ├── idnadata.py
│   │   ├── intranges.py
│   │   ├── package_data.py
│   │   ├── py.typed
│   │   └── uts46data.py
│   ├── idna-3.13.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── importlib_metadata/
│   │   ├── compat/
│   │   │   ├── __init__.py
│   │   │   ├── py311.py
│   │   │   └── py39.py
│   │   ├── __init__.py
│   │   ├── _adapters.py
│   │   ├── _collections.py
│   │   ├── _compat.py
│   │   ├── _functools.py
│   │   ├── _itertools.py
│   │   ├── _meta.py
│   │   ├── _text.py
│   │   ├── _typing.py
│   │   ├── diagnose.py
│   │   └── py.typed
│   ├── importlib_metadata-8.7.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── isapi/
│   │   ├── doc/
│   │   │   └── isapi.html
│   │   ├── samples/
│   │   │   ├── advanced.py
│   │   │   ├── README.txt
│   │   │   ├── redirector.py
│   │   │   ├── redirector_asynch.py
│   │   │   ├── redirector_with_filter.py
│   │   │   └── test.py
│   │   ├── test/
│   │   │   ├── extension_simple.py
│   │   │   └── README.txt
│   │   ├── __init__.py
│   │   ├── install.py
│   │   ├── isapicon.py
│   │   ├── PyISAPI_loader.dll
│   │   ├── README.txt
│   │   ├── simple.py
│   │   └── threaded_extension.py
│   ├── jaraco/
│   │   ├── classes/
│   │   │   ├── __init__.py
│   │   │   ├── ancestry.py
│   │   │   ├── meta.py
│   │   │   ├── properties.py
│   │   │   └── py.typed
│   │   ├── context/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   └── functools/
│   │       ├── __init__.py
│   │       ├── __init__.pyi
│   │       └── py.typed
│   ├── jaraco.classes-3.4.0.dist-info/
│   │   ├── INSTALLER
│   │   ├── LICENSE
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── jaraco_context-6.1.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── jaraco_functools-4.4.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── joserfc/
│   │   ├── _rfc7515/
│   │   │   ├── __init__.py
│   │   │   ├── compact.py
│   │   │   ├── json.py
│   │   │   ├── model.py
│   │   │   ├── registry.py
│   │   │   └── types.py
│   │   ├── _rfc7516/
│   │   │   ├── __init__.py
│   │   │   ├── compact.py
│   │   │   ├── json.py
│   │   │   ├── message.py
│   │   │   ├── models.py
│   │   │   ├── registry.py
│   │   │   └── types.py
│   │   ├── _rfc7517/
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── pem.py
│   │   │   └── types.py
│   │   ├── _rfc7518/
│   │   │   ├── __init__.py
│   │   │   ├── derive_key.py
│   │   │   ├── ec_key.py
│   │   │   ├── jwe_algs.py
│   │   │   ├── jwe_encs.py
│   │   │   ├── jwe_zips.py
│   │   │   ├── jws_algs.py
│   │   │   ├── oct_key.py
│   │   │   ├── rsa_key.py
│   │   │   └── util.py
│   │   ├── _rfc7519/
│   │   │   ├── __init__.py
│   │   │   ├── claims.py
│   │   │   └── security.py
│   │   ├── _rfc7638/
│   │   │   └── __init__.py
│   │   ├── _rfc7797/
│   │   │   ├── __init__.py
│   │   │   ├── compact.py
│   │   │   ├── json.py
│   │   │   └── util.py
│   │   ├── _rfc8037/
│   │   │   ├── __init__.py
│   │   │   ├── jws_eddsa.py
│   │   │   └── okp_key.py
│   │   ├── _rfc8812/
│   │   │   └── __init__.py
│   │   ├── _rfc9278/
│   │   │   └── __init__.py
│   │   ├── _rfc9864/
│   │   │   ├── __init__.py
│   │   │   └── jws_eddsa.py
│   │   ├── drafts/
│   │   │   ├── __init__.py
│   │   │   ├── jwe_chacha20.py
│   │   │   └── jwe_ecdh_1pu.py
│   │   ├── __init__.py
│   │   ├── _keys.py
│   │   ├── errors.py
│   │   ├── jwa.py
│   │   ├── jwe.py
│   │   ├── jwk.py
│   │   ├── jws.py
│   │   ├── jwt.py
│   │   ├── py.typed
│   │   ├── registry.py
│   │   └── util.py
│   ├── joserfc-1.6.4.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── jsonref-1.1.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── jsonschema/
│   │   ├── benchmarks/
│   │   │   ├── issue232/
│   │   │   ├── __init__.py
│   │   │   ├── const_vs_enum.py
│   │   │   ├── contains.py
│   │   │   ├── import_benchmark.py
│   │   │   ├── issue232.py
│   │   │   ├── json_schema_test_suite.py
│   │   │   ├── nested_schemas.py
│   │   │   ├── subcomponents.py
│   │   │   ├── unused_registry.py
│   │   │   ├── useless_applicator_schemas.py
│   │   │   ├── useless_keywords.py
│   │   │   └── validator_creation.py
│   │   ├── tests/
│   │   │   ├── typing/
│   │   │   ├── __init__.py
│   │   │   ├── _suite.py
│   │   │   ├── fuzz_validate.py
│   │   │   ├── test_cli.py
│   │   │   ├── test_deprecations.py
│   │   │   ├── test_exceptions.py
│   │   │   ├── test_format.py
│   │   │   ├── test_jsonschema_test_suite.py
│   │   │   ├── test_types.py
│   │   │   ├── test_utils.py
│   │   │   └── test_validators.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── _format.py
│   │   ├── _keywords.py
│   │   ├── _legacy_keywords.py
│   │   ├── _types.py
│   │   ├── _typing.py
│   │   ├── _utils.py
│   │   ├── cli.py
│   │   ├── exceptions.py
│   │   ├── protocols.py
│   │   └── validators.py
│   ├── jsonschema-4.26.0.dist-info/
│   │   ├── licenses/
│   │   │   └── COPYING
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── jsonschema_path/
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── file.py
│   │   │   ├── protocols.py
│   │   │   ├── requests.py
│   │   │   ├── urllib.py
│   │   │   └── utils.py
│   │   ├── __init__.py
│   │   ├── accessors.py
│   │   ├── caches.py
│   │   ├── loaders.py
│   │   ├── nodes.py
│   │   ├── paths.py
│   │   ├── py.typed
│   │   ├── readers.py
│   │   ├── resolvers.py
│   │   ├── retrievers.py
│   │   ├── typing.py
│   │   └── utils.py
│   ├── jsonschema_path-0.4.6.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── jsonschema_specifications/
│   │   ├── schemas/
│   │   │   ├── draft201909/
│   │   │   ├── draft202012/
│   │   │   ├── draft3/
│   │   │   ├── draft4/
│   │   │   ├── draft6/
│   │   │   └── draft7/
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   └── test_jsonschema_specifications.py
│   │   ├── __init__.py
│   │   └── _core.py
│   ├── jsonschema_specifications-2025.9.1.dist-info/
│   │   ├── licenses/
│   │   │   └── COPYING
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── jwt/
│   │   ├── __init__.py
│   │   ├── algorithms.py
│   │   ├── api_jwk.py
│   │   ├── api_jws.py
│   │   ├── api_jwt.py
│   │   ├── exceptions.py
│   │   ├── help.py
│   │   ├── jwk_set_cache.py
│   │   ├── jwks_client.py
│   │   ├── py.typed
│   │   ├── types.py
│   │   ├── utils.py
│   │   └── warnings.py
│   ├── key_value/
│   │   ├── aio/
│   │   │   ├── _utils/
│   │   │   ├── adapters/
│   │   │   ├── errors/
│   │   │   ├── protocols/
│   │   │   ├── stores/
│   │   │   ├── wrappers/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   └── __init__.py
│   ├── keyring/
│   │   ├── backends/
│   │   │   ├── macOS/
│   │   │   ├── __init__.py
│   │   │   ├── chainer.py
│   │   │   ├── fail.py
│   │   │   ├── kwallet.py
│   │   │   ├── libsecret.py
│   │   │   ├── null.py
│   │   │   ├── SecretService.py
│   │   │   └── Windows.py
│   │   ├── compat/
│   │   │   ├── __init__.py
│   │   │   ├── properties.py
│   │   │   └── py312.py
│   │   ├── testing/
│   │   │   ├── __init__.py
│   │   │   ├── backend.py
│   │   │   └── util.py
│   │   ├── util/
│   │   │   ├── __init__.py
│   │   │   └── platform_.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── backend.py
│   │   ├── backend_complete.bash
│   │   ├── backend_complete.zsh
│   │   ├── cli.py
│   │   ├── completion.py
│   │   ├── core.py
│   │   ├── credentials.py
│   │   ├── devpi_client.py
│   │   ├── errors.py
│   │   ├── http.py
│   │   └── py.typed
│   ├── keyring-25.7.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── markdown_it/
│   │   ├── cli/
│   │   │   ├── __init__.py
│   │   │   └── parse.py
│   │   ├── common/
│   │   │   ├── __init__.py
│   │   │   ├── entities.py
│   │   │   ├── html_blocks.py
│   │   │   ├── html_re.py
│   │   │   ├── normalize_url.py
│   │   │   └── utils.py
│   │   ├── helpers/
│   │   │   ├── __init__.py
│   │   │   ├── parse_link_destination.py
│   │   │   ├── parse_link_label.py
│   │   │   └── parse_link_title.py
│   │   ├── presets/
│   │   │   ├── __init__.py
│   │   │   ├── commonmark.py
│   │   │   ├── default.py
│   │   │   └── zero.py
│   │   ├── rules_block/
│   │   │   ├── __init__.py
│   │   │   ├── blockquote.py
│   │   │   ├── code.py
│   │   │   ├── fence.py
│   │   │   ├── heading.py
│   │   │   ├── hr.py
│   │   │   ├── html_block.py
│   │   │   ├── lheading.py
│   │   │   ├── list.py
│   │   │   ├── paragraph.py
│   │   │   ├── reference.py
│   │   │   ├── state_block.py
│   │   │   └── table.py
│   │   ├── rules_core/
│   │   │   ├── __init__.py
│   │   │   ├── block.py
│   │   │   ├── inline.py
│   │   │   ├── linkify.py
│   │   │   ├── normalize.py
│   │   │   ├── replacements.py
│   │   │   ├── smartquotes.py
│   │   │   ├── state_core.py
│   │   │   └── text_join.py
│   │   ├── rules_inline/
│   │   │   ├── __init__.py
│   │   │   ├── autolink.py
│   │   │   ├── backticks.py
│   │   │   ├── balance_pairs.py
│   │   │   ├── emphasis.py
│   │   │   ├── entity.py
│   │   │   ├── escape.py
│   │   │   ├── fragments_join.py
│   │   │   ├── html_inline.py
│   │   │   ├── image.py
│   │   │   ├── link.py
│   │   │   ├── linkify.py
│   │   │   ├── newline.py
│   │   │   ├── state_inline.py
│   │   │   ├── strikethrough.py
│   │   │   └── text.py
│   │   ├── __init__.py
│   │   ├── _compat.py
│   │   ├── _punycode.py
│   │   ├── main.py
│   │   ├── parser_block.py
│   │   ├── parser_core.py
│   │   ├── parser_inline.py
│   │   ├── port.yaml
│   │   ├── py.typed
│   │   ├── renderer.py
│   │   ├── ruler.py
│   │   ├── token.py
│   │   ├── tree.py
│   │   └── utils.py
│   ├── markdown_it_py-4.0.0.dist-info/
│   │   ├── licenses/
│   │   │   ├── LICENSE
│   │   │   └── LICENSE.markdown-it
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── mcp/
│   │   ├── cli/
│   │   │   ├── __init__.py
│   │   │   ├── claude.py
│   │   │   └── cli.py
│   │   ├── client/
│   │   │   ├── auth/
│   │   │   ├── experimental/
│   │   │   ├── stdio/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py
│   │   │   ├── session.py
│   │   │   ├── session_group.py
│   │   │   ├── sse.py
│   │   │   ├── streamable_http.py
│   │   │   └── websocket.py
│   │   ├── os/
│   │   │   ├── posix/
│   │   │   ├── win32/
│   │   │   └── __init__.py
│   │   ├── server/
│   │   │   ├── auth/
│   │   │   ├── experimental/
│   │   │   ├── fastmcp/
│   │   │   ├── lowlevel/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py
│   │   │   ├── elicitation.py
│   │   │   ├── models.py
│   │   │   ├── session.py
│   │   │   ├── sse.py
│   │   │   ├── stdio.py
│   │   │   ├── streamable_http.py
│   │   │   ├── streamable_http_manager.py
│   │   │   ├── transport_security.py
│   │   │   ├── validation.py
│   │   │   └── websocket.py
│   │   ├── shared/
│   │   │   ├── experimental/
│   │   │   ├── __init__.py
│   │   │   ├── _httpx_utils.py
│   │   │   ├── auth.py
│   │   │   ├── auth_utils.py
│   │   │   ├── context.py
│   │   │   ├── exceptions.py
│   │   │   ├── memory.py
│   │   │   ├── message.py
│   │   │   ├── metadata_utils.py
│   │   │   ├── progress.py
│   │   │   ├── response_router.py
│   │   │   ├── session.py
│   │   │   ├── tool_name_validation.py
│   │   │   └── version.py
│   │   ├── __init__.py
│   │   ├── py.typed
│   │   └── types.py
│   ├── mcp-1.27.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── mdurl/
│   │   ├── __init__.py
│   │   ├── _decode.py
│   │   ├── _encode.py
│   │   ├── _format.py
│   │   ├── _parse.py
│   │   ├── _url.py
│   │   └── py.typed
│   ├── mdurl-0.1.2.dist-info/
│   │   ├── INSTALLER
│   │   ├── LICENSE
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── more_itertools/
│   │   ├── __init__.py
│   │   ├── __init__.pyi
│   │   ├── more.py
│   │   ├── more.pyi
│   │   ├── py.typed
│   │   ├── recipes.py
│   │   └── recipes.pyi
│   ├── more_itertools-11.0.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── multipart/
│   │   ├── __init__.py
│   │   ├── decoders.py
│   │   ├── exceptions.py
│   │   └── multipart.py
│   ├── openapi_pydantic/
│   │   ├── v3/
│   │   │   ├── v3_0/
│   │   │   ├── v3_1/
│   │   │   ├── __init__.py
│   │   │   └── parser.py
│   │   ├── __init__.py
│   │   ├── compat.py
│   │   ├── py.typed
│   │   └── util.py
│   ├── openapi_pydantic-0.5.1.dist-info/
│   │   ├── INSTALLER
│   │   ├── LICENSE
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── opentelemetry/
│   │   ├── _events/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── _logs/
│   │   │   ├── _internal/
│   │   │   ├── severity/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── attributes/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── baggage/
│   │   │   ├── propagation/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── context/
│   │   │   ├── __init__.py
│   │   │   ├── context.py
│   │   │   ├── contextvars_context.py
│   │   │   └── py.typed
│   │   ├── environment_variables/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── metrics/
│   │   │   ├── _internal/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── propagate/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   ├── propagators/
│   │   │   ├── _envcarrier.py
│   │   │   ├── composite.py
│   │   │   ├── py.typed
│   │   │   └── textmap.py
│   │   ├── trace/
│   │   │   ├── propagation/
│   │   │   ├── __init__.py
│   │   │   ├── py.typed
│   │   │   ├── span.py
│   │   │   └── status.py
│   │   ├── util/
│   │   │   ├── _decorator.py
│   │   │   ├── _importlib_metadata.py
│   │   │   ├── _once.py
│   │   │   ├── _providers.py
│   │   │   ├── py.typed
│   │   │   ├── re.py
│   │   │   └── types.py
│   │   ├── version/
│   │   │   ├── __init__.py
│   │   │   └── py.typed
│   │   └── py.typed
│   ├── opentelemetry_api-1.41.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── packaging/
│   │   ├── licenses/
│   │   │   ├── __init__.py
│   │   │   └── _spdx.py
│   │   ├── __init__.py
│   │   ├── _elffile.py
│   │   ├── _manylinux.py
│   │   ├── _musllinux.py
│   │   ├── _parser.py
│   │   ├── _structures.py
│   │   ├── _tokenizer.py
│   │   ├── dependency_groups.py
│   │   ├── direct_url.py
│   │   ├── errors.py
│   │   ├── markers.py
│   │   ├── metadata.py
│   │   ├── py.typed
│   │   ├── pylock.py
│   │   ├── requirements.py
│   │   ├── specifiers.py
│   │   ├── tags.py
│   │   ├── utils.py
│   │   └── version.py
│   ├── packaging-26.2.dist-info/
│   │   ├── licenses/
│   │   │   ├── LICENSE
│   │   │   ├── LICENSE.APACHE
│   │   │   └── LICENSE.BSD
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pathable/
│   │   ├── __init__.py
│   │   ├── accessors.py
│   │   ├── parsers.py
│   │   ├── paths.py
│   │   ├── protocols.py
│   │   ├── py.typed
│   │   └── types.py
│   ├── pathable-0.5.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── platformdirs/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── _xdg.py
│   │   ├── android.py
│   │   ├── api.py
│   │   ├── macos.py
│   │   ├── py.typed
│   │   ├── unix.py
│   │   ├── version.py
│   │   └── windows.py
│   ├── platformdirs-4.9.6.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── py_key_value_aio-0.4.4.dist-info/
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pycparser/
│   │   ├── __init__.py
│   │   ├── _ast_gen.py
│   │   ├── _c_ast.cfg
│   │   ├── ast_transforms.py
│   │   ├── c_ast.py
│   │   ├── c_generator.py
│   │   ├── c_lexer.py
│   │   └── c_parser.py
│   ├── pycparser-3.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── pydantic/
│   │   ├── _internal/
│   │   │   ├── __init__.py
│   │   │   ├── _config.py
│   │   │   ├── _core_metadata.py
│   │   │   ├── _core_utils.py
│   │   │   ├── _dataclasses.py
│   │   │   ├── _decorators.py
│   │   │   ├── _decorators_v1.py
│   │   │   ├── _discriminated_union.py
│   │   │   ├── _docs_extraction.py
│   │   │   ├── _fields.py
│   │   │   ├── _forward_ref.py
│   │   │   ├── _generate_schema.py
│   │   │   ├── _generics.py
│   │   │   ├── _git.py
│   │   │   ├── _import_utils.py
│   │   │   ├── _internal_dataclass.py
│   │   │   ├── _known_annotated_metadata.py
│   │   │   ├── _mock_val_ser.py
│   │   │   ├── _model_construction.py
│   │   │   ├── _namespace_utils.py
│   │   │   ├── _repr.py
│   │   │   ├── _schema_gather.py
│   │   │   ├── _schema_generation_shared.py
│   │   │   ├── _serializers.py
│   │   │   ├── _signature.py
│   │   │   ├── _typing_extra.py
│   │   │   ├── _utils.py
│   │   │   ├── _validate_call.py
│   │   │   └── _validators.py
│   │   ├── deprecated/
│   │   │   ├── __init__.py
│   │   │   ├── class_validators.py
│   │   │   ├── config.py
│   │   │   ├── copy_internals.py
│   │   │   ├── decorator.py
│   │   │   ├── json.py
│   │   │   ├── parse.py
│   │   │   └── tools.py
│   │   ├── experimental/
│   │   │   ├── __init__.py
│   │   │   ├── arguments_schema.py
│   │   │   ├── missing_sentinel.py
│   │   │   └── pipeline.py
│   │   ├── plugin/
│   │   │   ├── __init__.py
│   │   │   ├── _loader.py
│   │   │   └── _schema_validator.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── _hypothesis_plugin.py
│   │   │   ├── annotated_types.py
│   │   │   ├── class_validators.py
│   │   │   ├── color.py
│   │   │   ├── config.py
│   │   │   ├── dataclasses.py
│   │   │   ├── datetime_parse.py
│   │   │   ├── decorator.py
│   │   │   ├── env_settings.py
│   │   │   ├── error_wrappers.py
│   │   │   ├── errors.py
│   │   │   ├── fields.py
│   │   │   ├── generics.py
│   │   │   ├── json.py
│   │   │   ├── main.py
│   │   │   ├── mypy.py
│   │   │   ├── networks.py
│   │   │   ├── parse.py
│   │   │   ├── py.typed
│   │   │   ├── schema.py
│   │   │   ├── tools.py
│   │   │   ├── types.py
│   │   │   ├── typing.py
│   │   │   ├── utils.py
│   │   │   ├── validators.py
│   │   │   └── version.py
│   │   ├── __init__.py
│   │   ├── _migration.py
│   │   ├── alias_generators.py
│   │   ├── aliases.py
│   │   ├── annotated_handlers.py
│   │   ├── class_validators.py
│   │   ├── color.py
│   │   ├── config.py
│   │   ├── dataclasses.py
│   │   ├── datetime_parse.py
│   │   ├── decorator.py
│   │   ├── env_settings.py
│   │   ├── error_wrappers.py
│   │   ├── errors.py
│   │   ├── fields.py
│   │   ├── functional_serializers.py
│   │   ├── functional_validators.py
│   │   ├── generics.py
│   │   ├── json.py
│   │   ├── json_schema.py
│   │   ├── main.py
│   │   ├── mypy.py
│   │   ├── networks.py
│   │   ├── parse.py
│   │   ├── py.typed
│   │   ├── root_model.py
│   │   ├── schema.py
│   │   ├── tools.py
│   │   ├── type_adapter.py
│   │   ├── types.py
│   │   ├── typing.py
│   │   ├── utils.py
│   │   ├── validate_call_decorator.py
│   │   ├── validators.py
│   │   ├── version.py
│   │   └── warnings.py
│   ├── pydantic-2.13.3.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pydantic_core/
│   │   ├── __init__.py
│   │   ├── _pydantic_core.cp314-win_amd64.pyd
│   │   ├── _pydantic_core.pyi
│   │   ├── core_schema.py
│   │   └── py.typed
│   ├── pydantic_core-2.46.3.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── sboms/
│   │   │   └── pydantic-core.cyclonedx.json
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pydantic_settings/
│   │   ├── sources/
│   │   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── types.py
│   │   │   └── utils.py
│   │   ├── __init__.py
│   │   ├── exceptions.py
│   │   ├── main.py
│   │   ├── py.typed
│   │   ├── utils.py
│   │   └── version.py
│   ├── pydantic_settings-2.14.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pygments/
│   │   ├── filters/
│   │   │   └── __init__.py
│   │   ├── formatters/
│   │   │   ├── __init__.py
│   │   │   ├── _mapping.py
│   │   │   ├── bbcode.py
│   │   │   ├── groff.py
│   │   │   ├── html.py
│   │   │   ├── img.py
│   │   │   ├── irc.py
│   │   │   ├── latex.py
│   │   │   ├── other.py
│   │   │   ├── pangomarkup.py
│   │   │   ├── rtf.py
│   │   │   ├── svg.py
│   │   │   ├── terminal.py
│   │   │   └── terminal256.py
│   │   ├── lexers/
│   │   │   ├── __init__.py
│   │   │   ├── _ada_builtins.py
│   │   │   ├── _asy_builtins.py
│   │   │   ├── _cl_builtins.py
│   │   │   ├── _cocoa_builtins.py
│   │   │   ├── _csound_builtins.py
│   │   │   ├── _css_builtins.py
│   │   │   ├── _googlesql_builtins.py
│   │   │   ├── _julia_builtins.py
│   │   │   ├── _lasso_builtins.py
│   │   │   ├── _lilypond_builtins.py
│   │   │   ├── _lua_builtins.py
│   │   │   ├── _luau_builtins.py
│   │   │   ├── _mapping.py
│   │   │   ├── _mql_builtins.py
│   │   │   ├── _mysql_builtins.py
│   │   │   ├── _openedge_builtins.py
│   │   │   ├── _php_builtins.py
│   │   │   ├── _postgres_builtins.py
│   │   │   ├── _qlik_builtins.py
│   │   │   ├── _scheme_builtins.py
│   │   │   ├── _scilab_builtins.py
│   │   │   ├── _sourcemod_builtins.py
│   │   │   ├── _sql_builtins.py
│   │   │   ├── _stan_builtins.py
│   │   │   ├── _stata_builtins.py
│   │   │   ├── _tsql_builtins.py
│   │   │   ├── _usd_builtins.py
│   │   │   ├── _vbscript_builtins.py
│   │   │   ├── _vim_builtins.py
│   │   │   ├── actionscript.py
│   │   │   ├── ada.py
│   │   │   ├── agile.py
│   │   │   ├── algebra.py
│   │   │   ├── ambient.py
│   │   │   ├── amdgpu.py
│   │   │   ├── ampl.py
│   │   │   ├── apdlexer.py
│   │   │   ├── apl.py
│   │   │   ├── archetype.py
│   │   │   ├── arrow.py
│   │   │   ├── arturo.py
│   │   │   ├── asc.py
│   │   │   ├── asm.py
│   │   │   ├── asn1.py
│   │   │   ├── automation.py
│   │   │   ├── bare.py
│   │   │   ├── basic.py
│   │   │   ├── bdd.py
│   │   │   ├── berry.py
│   │   │   ├── bibtex.py
│   │   │   ├── blueprint.py
│   │   │   ├── boa.py
│   │   │   ├── bqn.py
│   │   │   ├── business.py
│   │   │   ├── c_cpp.py
│   │   │   ├── c_like.py
│   │   │   ├── capnproto.py
│   │   │   ├── carbon.py
│   │   │   ├── cddl.py
│   │   │   ├── chapel.py
│   │   │   ├── clean.py
│   │   │   ├── codeql.py
│   │   │   ├── comal.py
│   │   │   ├── compiled.py
│   │   │   ├── configs.py
│   │   │   ├── console.py
│   │   │   ├── cplint.py
│   │   │   ├── crystal.py
│   │   │   ├── csound.py
│   │   │   ├── css.py
│   │   │   ├── d.py
│   │   │   ├── dalvik.py
│   │   │   ├── data.py
│   │   │   ├── dax.py
│   │   │   ├── devicetree.py
│   │   │   ├── diff.py
│   │   │   ├── dns.py
│   │   │   ├── dotnet.py
│   │   │   ├── dsls.py
│   │   │   ├── dylan.py
│   │   │   ├── ecl.py
│   │   │   ├── eiffel.py
│   │   │   ├── elm.py
│   │   │   ├── elpi.py
│   │   │   ├── email.py
│   │   │   ├── erlang.py
│   │   │   ├── esoteric.py
│   │   │   ├── ezhil.py
│   │   │   ├── factor.py
│   │   │   ├── fantom.py
│   │   │   ├── felix.py
│   │   │   ├── fift.py
│   │   │   ├── floscript.py
│   │   │   ├── forth.py
│   │   │   ├── fortran.py
│   │   │   ├── foxpro.py
│   │   │   ├── freefem.py
│   │   │   ├── func.py
│   │   │   ├── functional.py
│   │   │   ├── futhark.py
│   │   │   ├── gcodelexer.py
│   │   │   ├── gdscript.py
│   │   │   ├── gleam.py
│   │   │   ├── go.py
│   │   │   ├── grammar_notation.py
│   │   │   ├── graph.py
│   │   │   ├── graphics.py
│   │   │   ├── graphql.py
│   │   │   ├── graphviz.py
│   │   │   ├── gsql.py
│   │   │   ├── hare.py
│   │   │   ├── haskell.py
│   │   │   ├── haxe.py
│   │   │   ├── hdl.py
│   │   │   ├── hexdump.py
│   │   │   ├── html.py
│   │   │   ├── idl.py
│   │   │   ├── igor.py
│   │   │   ├── inferno.py
│   │   │   ├── installers.py
│   │   │   ├── int_fiction.py
│   │   │   ├── iolang.py
│   │   │   ├── j.py
│   │   │   ├── javascript.py
│   │   │   ├── jmespath.py
│   │   │   ├── jslt.py
│   │   │   ├── json5.py
│   │   │   ├── jsonnet.py
│   │   │   ├── jsx.py
│   │   │   ├── julia.py
│   │   │   ├── jvm.py
│   │   │   ├── kuin.py
│   │   │   ├── kusto.py
│   │   │   ├── ldap.py
│   │   │   ├── lean.py
│   │   │   ├── lilypond.py
│   │   │   ├── lisp.py
│   │   │   ├── macaulay2.py
│   │   │   ├── make.py
│   │   │   ├── maple.py
│   │   │   ├── markup.py
│   │   │   ├── math.py
│   │   │   ├── matlab.py
│   │   │   ├── maxima.py
│   │   │   ├── meson.py
│   │   │   ├── mime.py
│   │   │   ├── minecraft.py
│   │   │   ├── mips.py
│   │   │   ├── ml.py
│   │   │   ├── modeling.py
│   │   │   ├── modula2.py
│   │   │   ├── mojo.py
│   │   │   ├── monte.py
│   │   │   ├── mosel.py
│   │   │   ├── ncl.py
│   │   │   ├── nimrod.py
│   │   │   ├── nit.py
│   │   │   ├── nix.py
│   │   │   ├── numbair.py
│   │   │   ├── oberon.py
│   │   │   ├── objective.py
│   │   │   ├── ooc.py
│   │   │   ├── openscad.py
│   │   │   ├── other.py
│   │   │   ├── parasail.py
│   │   │   ├── parsers.py
│   │   │   ├── pascal.py
│   │   │   ├── pawn.py
│   │   │   ├── pddl.py
│   │   │   ├── perl.py
│   │   │   ├── phix.py
│   │   │   ├── php.py
│   │   │   ├── pointless.py
│   │   │   ├── pony.py
│   │   │   ├── praat.py
│   │   │   ├── procfile.py
│   │   │   ├── prolog.py
│   │   │   ├── promql.py
│   │   │   ├── prql.py
│   │   │   ├── ptx.py
│   │   │   ├── python.py
│   │   │   ├── q.py
│   │   │   ├── qlik.py
│   │   │   ├── qvt.py
│   │   │   ├── r.py
│   │   │   ├── rdf.py
│   │   │   ├── rebol.py
│   │   │   ├── rego.py
│   │   │   ├── rell.py
│   │   │   ├── resource.py
│   │   │   ├── ride.py
│   │   │   ├── rita.py
│   │   │   ├── rnc.py
│   │   │   ├── roboconf.py
│   │   │   ├── robotframework.py
│   │   │   ├── ruby.py
│   │   │   ├── rust.py
│   │   │   ├── sas.py
│   │   │   ├── savi.py
│   │   │   ├── scdoc.py
│   │   │   ├── scripting.py
│   │   │   ├── sgf.py
│   │   │   ├── shell.py
│   │   │   ├── sieve.py
│   │   │   ├── slash.py
│   │   │   ├── smalltalk.py
│   │   │   ├── smithy.py
│   │   │   ├── smv.py
│   │   │   ├── snobol.py
│   │   │   ├── solidity.py
│   │   │   ├── soong.py
│   │   │   ├── sophia.py
│   │   │   ├── special.py
│   │   │   ├── spice.py
│   │   │   ├── sql.py
│   │   │   ├── srcinfo.py
│   │   │   ├── stata.py
│   │   │   ├── supercollider.py
│   │   │   ├── tablegen.py
│   │   │   ├── tact.py
│   │   │   ├── tal.py
│   │   │   ├── tcl.py
│   │   │   ├── teal.py
│   │   │   ├── templates.py
│   │   │   ├── teraterm.py
│   │   │   ├── testing.py
│   │   │   ├── text.py
│   │   │   ├── textedit.py
│   │   │   ├── textfmts.py
│   │   │   ├── theorem.py
│   │   │   ├── thingsdb.py
│   │   │   ├── tlb.py
│   │   │   ├── tls.py
│   │   │   ├── tnt.py
│   │   │   ├── trafficscript.py
│   │   │   ├── typoscript.py
│   │   │   ├── typst.py
│   │   │   ├── ul4.py
│   │   │   ├── unicon.py
│   │   │   ├── urbi.py
│   │   │   ├── usd.py
│   │   │   ├── varnish.py
│   │   │   ├── verification.py
│   │   │   ├── verifpal.py
│   │   │   ├── vip.py
│   │   │   ├── vyper.py
│   │   │   ├── web.py
│   │   │   ├── webassembly.py
│   │   │   ├── webidl.py
│   │   │   ├── webmisc.py
│   │   │   ├── wgsl.py
│   │   │   ├── whiley.py
│   │   │   ├── wowtoc.py
│   │   │   ├── wren.py
│   │   │   ├── x10.py
│   │   │   ├── xorg.py
│   │   │   ├── yang.py
│   │   │   ├── yara.py
│   │   │   └── zig.py
│   │   ├── styles/
│   │   │   ├── __init__.py
│   │   │   ├── _mapping.py
│   │   │   ├── abap.py
│   │   │   ├── algol.py
│   │   │   ├── algol_nu.py
│   │   │   ├── arduino.py
│   │   │   ├── autumn.py
│   │   │   ├── borland.py
│   │   │   ├── bw.py
│   │   │   ├── coffee.py
│   │   │   ├── colorful.py
│   │   │   ├── default.py
│   │   │   ├── dracula.py
│   │   │   ├── emacs.py
│   │   │   ├── friendly.py
│   │   │   ├── friendly_grayscale.py
│   │   │   ├── fruity.py
│   │   │   ├── gh_dark.py
│   │   │   ├── gruvbox.py
│   │   │   ├── igor.py
│   │   │   ├── inkpot.py
│   │   │   ├── lightbulb.py
│   │   │   ├── lilypond.py
│   │   │   ├── lovelace.py
│   │   │   ├── manni.py
│   │   │   ├── material.py
│   │   │   ├── monokai.py
│   │   │   ├── murphy.py
│   │   │   ├── native.py
│   │   │   ├── nord.py
│   │   │   ├── onedark.py
│   │   │   ├── paraiso_dark.py
│   │   │   ├── paraiso_light.py
│   │   │   ├── pastie.py
│   │   │   ├── perldoc.py
│   │   │   ├── rainbow_dash.py
│   │   │   ├── rrt.py
│   │   │   ├── sas.py
│   │   │   ├── solarized.py
│   │   │   ├── staroffice.py
│   │   │   ├── stata_dark.py
│   │   │   ├── stata_light.py
│   │   │   ├── tango.py
│   │   │   ├── trac.py
│   │   │   ├── vim.py
│   │   │   ├── vs.py
│   │   │   ├── xcode.py
│   │   │   └── zenburn.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cmdline.py
│   │   ├── console.py
│   │   ├── filter.py
│   │   ├── formatter.py
│   │   ├── lexer.py
│   │   ├── modeline.py
│   │   ├── plugin.py
│   │   ├── regexopt.py
│   │   ├── scanner.py
│   │   ├── sphinxext.py
│   │   ├── style.py
│   │   ├── token.py
│   │   ├── unistring.py
│   │   └── util.py
│   ├── pygments-2.20.0.dist-info/
│   │   ├── licenses/
│   │   │   ├── AUTHORS
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pyjwt-2.12.1.dist-info/
│   │   ├── licenses/
│   │   │   ├── AUTHORS.rst
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── pyperclip/
│   │   ├── __init__.py
│   │   └── __main__.py
│   ├── pyperclip-1.11.0.dist-info/
│   │   ├── licenses/
│   │   │   ├── AUTHORS.txt
│   │   │   └── LICENSE.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── python_dotenv-1.2.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── python_multipart/
│   │   ├── __init__.py
│   │   ├── decoders.py
│   │   ├── exceptions.py
│   │   ├── multipart.py
│   │   └── py.typed
│   ├── python_multipart-0.0.27.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── pythonwin/
│   │   ├── pywin/
│   │   │   ├── debugger/
│   │   │   ├── Demos/
│   │   │   ├── dialogs/
│   │   │   ├── docking/
│   │   │   ├── framework/
│   │   │   ├── idle/
│   │   │   ├── mfc/
│   │   │   ├── scintilla/
│   │   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── default.cfg
│   │   │   └── IDLE.cfg
│   │   ├── dde.pyd
│   │   ├── license.txt
│   │   ├── mfc140u.dll
│   │   ├── Pythonwin.exe
│   │   ├── scintilla.dll
│   │   ├── start_pythonwin.pyw
│   │   ├── win32ui.pyd
│   │   └── win32uiole.pyd
│   ├── pywin32-311.dist-info/
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── pywin32_ctypes-0.2.3.dist-info/
│   │   ├── INSTALLER
│   │   ├── LICENSE.txt
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── pywin32_system32/
│   │   ├── pythoncom314.dll
│   │   └── pywintypes314.dll
│   ├── pyyaml-6.0.3.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── referencing/
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_core.py
│   │   │   ├── test_exceptions.py
│   │   │   ├── test_jsonschema.py
│   │   │   ├── test_referencing_suite.py
│   │   │   └── test_retrieval.py
│   │   ├── __init__.py
│   │   ├── _attrs.py
│   │   ├── _attrs.pyi
│   │   ├── _core.py
│   │   ├── exceptions.py
│   │   ├── jsonschema.py
│   │   ├── py.typed
│   │   ├── retrieval.py
│   │   └── typing.py
│   ├── referencing-0.37.0.dist-info/
│   │   ├── licenses/
│   │   │   └── COPYING
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── rich/
│   │   ├── _unicode_data/
│   │   │   ├── __init__.py
│   │   │   ├── _versions.py
│   │   │   ├── unicode10-0-0.py
│   │   │   ├── unicode11-0-0.py
│   │   │   ├── unicode12-0-0.py
│   │   │   ├── unicode12-1-0.py
│   │   │   ├── unicode13-0-0.py
│   │   │   ├── unicode14-0-0.py
│   │   │   ├── unicode15-0-0.py
│   │   │   ├── unicode15-1-0.py
│   │   │   ├── unicode16-0-0.py
│   │   │   ├── unicode17-0-0.py
│   │   │   ├── unicode4-1-0.py
│   │   │   ├── unicode5-0-0.py
│   │   │   ├── unicode5-1-0.py
│   │   │   ├── unicode5-2-0.py
│   │   │   ├── unicode6-0-0.py
│   │   │   ├── unicode6-1-0.py
│   │   │   ├── unicode6-2-0.py
│   │   │   ├── unicode6-3-0.py
│   │   │   ├── unicode7-0-0.py
│   │   │   ├── unicode8-0-0.py
│   │   │   └── unicode9-0-0.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── _emoji_codes.py
│   │   ├── _emoji_replace.py
│   │   ├── _export_format.py
│   │   ├── _extension.py
│   │   ├── _fileno.py
│   │   ├── _inspect.py
│   │   ├── _log_render.py
│   │   ├── _loop.py
│   │   ├── _null_file.py
│   │   ├── _palettes.py
│   │   ├── _pick.py
│   │   ├── _ratio.py
│   │   ├── _spinners.py
│   │   ├── _stack.py
│   │   ├── _timer.py
│   │   ├── _win32_console.py
│   │   ├── _windows.py
│   │   ├── _windows_renderer.py
│   │   ├── _wrap.py
│   │   ├── abc.py
│   │   ├── align.py
│   │   ├── ansi.py
│   │   ├── bar.py
│   │   ├── box.py
│   │   ├── cells.py
│   │   ├── color.py
│   │   ├── color_triplet.py
│   │   ├── columns.py
│   │   ├── console.py
│   │   ├── constrain.py
│   │   ├── containers.py
│   │   ├── control.py
│   │   ├── default_styles.py
│   │   ├── diagnose.py
│   │   ├── emoji.py
│   │   ├── errors.py
│   │   ├── file_proxy.py
│   │   ├── filesize.py
│   │   ├── highlighter.py
│   │   ├── json.py
│   │   ├── jupyter.py
│   │   ├── layout.py
│   │   ├── live.py
│   │   ├── live_render.py
│   │   ├── logging.py
│   │   ├── markdown.py
│   │   ├── markup.py
│   │   ├── measure.py
│   │   ├── padding.py
│   │   ├── pager.py
│   │   ├── palette.py
│   │   ├── panel.py
│   │   ├── pretty.py
│   │   ├── progress.py
│   │   ├── progress_bar.py
│   │   ├── prompt.py
│   │   ├── protocol.py
│   │   ├── py.typed
│   │   ├── region.py
│   │   ├── repr.py
│   │   ├── rule.py
│   │   ├── scope.py
│   │   ├── screen.py
│   │   ├── segment.py
│   │   ├── spinner.py
│   │   ├── status.py
│   │   ├── style.py
│   │   ├── styled.py
│   │   ├── syntax.py
│   │   ├── table.py
│   │   ├── terminal_theme.py
│   │   ├── text.py
│   │   ├── theme.py
│   │   ├── themes.py
│   │   ├── traceback.py
│   │   └── tree.py
│   ├── rich-15.0.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── rich_rst/
│   │   ├── __init__.py
│   │   └── __main__.py
│   ├── rich_rst-1.3.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── rpds/
│   │   ├── __init__.py
│   │   ├── __init__.pyi
│   │   ├── py.typed
│   │   └── rpds.cp314-win_amd64.pyd
│   ├── rpds_py-0.30.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── sse_starlette/
│   │   ├── __init__.py
│   │   ├── _utils.py
│   │   ├── event.py
│   │   ├── py.typed
│   │   └── sse.py
│   ├── sse_starlette-3.4.1.dist-info/
│   │   ├── licenses/
│   │   │   ├── AUTHORS
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── starlette/
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── authentication.py
│   │   │   ├── base.py
│   │   │   ├── cors.py
│   │   │   ├── errors.py
│   │   │   ├── exceptions.py
│   │   │   ├── gzip.py
│   │   │   ├── httpsredirect.py
│   │   │   ├── sessions.py
│   │   │   ├── trustedhost.py
│   │   │   └── wsgi.py
│   │   ├── __init__.py
│   │   ├── _exception_handler.py
│   │   ├── _utils.py
│   │   ├── applications.py
│   │   ├── authentication.py
│   │   ├── background.py
│   │   ├── concurrency.py
│   │   ├── config.py
│   │   ├── convertors.py
│   │   ├── datastructures.py
│   │   ├── endpoints.py
│   │   ├── exceptions.py
│   │   ├── formparsers.py
│   │   ├── py.typed
│   │   ├── requests.py
│   │   ├── responses.py
│   │   ├── routing.py
│   │   ├── schemas.py
│   │   ├── staticfiles.py
│   │   ├── status.py
│   │   ├── templating.py
│   │   ├── testclient.py
│   │   ├── types.py
│   │   └── websockets.py
│   ├── starlette-1.0.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── typing_extensions-4.15.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── typing_inspection/
│   │   ├── __init__.py
│   │   ├── introspection.py
│   │   ├── py.typed
│   │   ├── typing_objects.py
│   │   └── typing_objects.pyi
│   ├── typing_inspection-0.4.2.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── uncalled_for/
│   │   ├── __init__.py
│   │   ├── annotations.py
│   │   ├── base.py
│   │   ├── functional.py
│   │   ├── introspection.py
│   │   ├── py.typed
│   │   ├── resolution.py
│   │   ├── shared.py
│   │   └── validation.py
│   ├── uncalled_for-0.3.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── uvicorn/
│   │   ├── lifespan/
│   │   │   ├── __init__.py
│   │   │   ├── off.py
│   │   │   └── on.py
│   │   ├── loops/
│   │   │   ├── __init__.py
│   │   │   ├── asyncio.py
│   │   │   ├── auto.py
│   │   │   └── uvloop.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── asgi2.py
│   │   │   ├── message_logger.py
│   │   │   ├── proxy_headers.py
│   │   │   └── wsgi.py
│   │   ├── protocols/
│   │   │   ├── http/
│   │   │   ├── websockets/
│   │   │   ├── __init__.py
│   │   │   └── utils.py
│   │   ├── supervisors/
│   │   │   ├── __init__.py
│   │   │   ├── basereload.py
│   │   │   ├── multiprocess.py
│   │   │   ├── statreload.py
│   │   │   └── watchfilesreload.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── _compat.py
│   │   ├── _subprocess.py
│   │   ├── _types.py
│   │   ├── config.py
│   │   ├── importer.py
│   │   ├── logging.py
│   │   ├── main.py
│   │   ├── py.typed
│   │   ├── server.py
│   │   └── workers.py
│   ├── uvicorn-0.46.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE.md
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── watchfiles/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── _rust_notify.cp314-win_amd64.pyd
│   │   ├── _rust_notify.pyi
│   │   ├── cli.py
│   │   ├── filters.py
│   │   ├── main.py
│   │   ├── py.typed
│   │   ├── run.py
│   │   └── version.py
│   ├── watchfiles-1.1.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   └── WHEEL
│   ├── websockets/
│   │   ├── asyncio/
│   │   │   ├── __init__.py
│   │   │   ├── async_timeout.py
│   │   │   ├── client.py
│   │   │   ├── compatibility.py
│   │   │   ├── connection.py
│   │   │   ├── messages.py
│   │   │   ├── router.py
│   │   │   └── server.py
│   │   ├── extensions/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── permessage_deflate.py
│   │   ├── legacy/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── client.py
│   │   │   ├── exceptions.py
│   │   │   ├── framing.py
│   │   │   ├── handshake.py
│   │   │   ├── http.py
│   │   │   ├── protocol.py
│   │   │   └── server.py
│   │   ├── sync/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── connection.py
│   │   │   ├── messages.py
│   │   │   ├── router.py
│   │   │   ├── server.py
│   │   │   └── utils.py
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── auth.py
│   │   ├── cli.py
│   │   ├── client.py
│   │   ├── connection.py
│   │   ├── datastructures.py
│   │   ├── exceptions.py
│   │   ├── frames.py
│   │   ├── headers.py
│   │   ├── http.py
│   │   ├── http11.py
│   │   ├── imports.py
│   │   ├── protocol.py
│   │   ├── proxy.py
│   │   ├── py.typed
│   │   ├── server.py
│   │   ├── speedups.c
│   │   ├── speedups.cp314-win_amd64.pyd
│   │   ├── speedups.pyi
│   │   ├── streams.py
│   │   ├── typing.py
│   │   ├── uri.py
│   │   ├── utils.py
│   │   └── version.py
│   ├── websockets-16.0.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── entry_points.txt
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── win32/
│   │   ├── Demos/
│   │   │   ├── c_extension/
│   │   │   ├── dde/
│   │   │   ├── images/
│   │   │   ├── pipes/
│   │   │   ├── security/
│   │   │   ├── service/
│   │   │   ├── win32wnet/
│   │   │   ├── BackupRead_BackupWrite.py
│   │   │   ├── BackupSeek_streamheaders.py
│   │   │   ├── CopyFileEx.py
│   │   │   ├── CreateFileTransacted_MiniVersion.py
│   │   │   ├── desktopmanager.py
│   │   │   ├── eventLogDemo.py
│   │   │   ├── EvtFormatMessage.py
│   │   │   ├── EvtSubscribe_pull.py
│   │   │   ├── EvtSubscribe_push.py
│   │   │   ├── FileSecurityTest.py
│   │   │   ├── getfilever.py
│   │   │   ├── GetSaveFileName.py
│   │   │   ├── mmapfile_demo.py
│   │   │   ├── NetValidatePasswordPolicy.py
│   │   │   ├── OpenEncryptedFileRaw.py
│   │   │   ├── print_desktop.py
│   │   │   ├── rastest.py
│   │   │   ├── RegCreateKeyTransacted.py
│   │   │   ├── RegRestoreKey.py
│   │   │   ├── SystemParametersInfo.py
│   │   │   ├── timer_demo.py
│   │   │   ├── win32clipboard_bitmapdemo.py
│   │   │   ├── win32clipboardDemo.py
│   │   │   ├── win32comport_demo.py
│   │   │   ├── win32console_demo.py
│   │   │   ├── win32cred_demo.py
│   │   │   ├── win32fileDemo.py
│   │   │   ├── win32gui_demo.py
│   │   │   ├── win32gui_devicenotify.py
│   │   │   ├── win32gui_dialog.py
│   │   │   ├── win32gui_menu.py
│   │   │   ├── win32gui_taskbar.py
│   │   │   ├── win32netdemo.py
│   │   │   ├── win32rcparser_demo.py
│   │   │   ├── win32servicedemo.py
│   │   │   ├── win32ts_logoff_disconnected.py
│   │   │   └── winprocess.py
│   │   ├── include/
│   │   │   └── PyWinTypes.h
│   │   ├── lib/
│   │   │   ├── _win32verstamp_pywin32ctypes.py
│   │   │   ├── afxres.py
│   │   │   ├── commctrl.py
│   │   │   ├── mmsystem.py
│   │   │   ├── netbios.py
│   │   │   ├── ntsecuritycon.py
│   │   │   ├── pywin32_bootstrap.py
│   │   │   ├── pywin32_testutil.py
│   │   │   ├── pywintypes.py
│   │   │   ├── rasutil.py
│   │   │   ├── regcheck.py
│   │   │   ├── regutil.py
│   │   │   ├── sspi.py
│   │   │   ├── sspicon.py
│   │   │   ├── win2kras.py
│   │   │   ├── win32con.py
│   │   │   ├── win32cryptcon.py
│   │   │   ├── win32evtlogutil.py
│   │   │   ├── win32gui_struct.py
│   │   │   ├── win32inetcon.py
│   │   │   ├── win32netcon.py
│   │   │   ├── win32pdhquery.py
│   │   │   ├── win32pdhutil.py
│   │   │   ├── win32rcparser.py
│   │   │   ├── win32serviceutil.py
│   │   │   ├── win32timezone.py
│   │   │   ├── win32traceutil.py
│   │   │   ├── win32verstamp.py
│   │   │   ├── winerror.py
│   │   │   ├── winioctlcon.py
│   │   │   ├── winnt.py
│   │   │   ├── winperf.py
│   │   │   └── winxptheme.py
│   │   ├── libs/
│   │   │   └── pywintypes.lib
│   │   ├── scripts/
│   │   │   ├── VersionStamp/
│   │   │   ├── backupEventLog.py
│   │   │   ├── ControlService.py
│   │   │   ├── h2py.py
│   │   │   ├── killProcName.py
│   │   │   ├── pywin32_postinstall.py
│   │   │   ├── pywin32_testall.py
│   │   │   ├── rasutil.py
│   │   │   ├── regsetup.py
│   │   │   └── setup_d.py
│   │   ├── test/
│   │   │   ├── win32rcparser/
│   │   │   ├── handles.py
│   │   │   ├── test_clipboard.py
│   │   │   ├── test_exceptions.py
│   │   │   ├── test_odbc.py
│   │   │   ├── test_pywintypes.py
│   │   │   ├── test_security.py
│   │   │   ├── test_sspi.py
│   │   │   ├── test_win32api.py
│   │   │   ├── test_win32clipboard.py
│   │   │   ├── test_win32cred.py
│   │   │   ├── test_win32crypt.py
│   │   │   ├── test_win32event.py
│   │   │   ├── test_win32file.py
│   │   │   ├── test_win32gui.py
│   │   │   ├── test_win32guistruct.py
│   │   │   ├── test_win32inet.py
│   │   │   ├── test_win32net.py
│   │   │   ├── test_win32pipe.py
│   │   │   ├── test_win32print.py
│   │   │   ├── test_win32profile.py
│   │   │   ├── test_win32rcparser.py
│   │   │   ├── test_win32timezone.py
│   │   │   ├── test_win32trace.py
│   │   │   ├── test_win32ts.py
│   │   │   ├── test_win32wnet.py
│   │   │   └── testall.py
│   │   ├── _win32sysloader.pyd
│   │   ├── _winxptheme.pyd
│   │   ├── license.txt
│   │   ├── mmapfile.pyd
│   │   ├── odbc.pyd
│   │   ├── perfmon.pyd
│   │   ├── perfmondata.dll
│   │   ├── pythonservice.exe
│   │   ├── servicemanager.pyd
│   │   ├── timer.pyd
│   │   ├── win32api.pyd
│   │   ├── win32clipboard.pyd
│   │   ├── win32console.pyd
│   │   ├── win32cred.pyd
│   │   ├── win32crypt.pyd
│   │   ├── win32event.pyd
│   │   ├── win32evtlog.pyd
│   │   ├── win32file.pyd
│   │   ├── win32gui.pyd
│   │   ├── win32help.pyd
│   │   ├── win32inet.pyd
│   │   ├── win32job.pyd
│   │   ├── win32lz.pyd
│   │   ├── win32net.pyd
│   │   ├── win32pdh.pyd
│   │   ├── win32pipe.pyd
│   │   ├── win32print.pyd
│   │   ├── win32process.pyd
│   │   ├── win32profile.pyd
│   │   ├── win32ras.pyd
│   │   ├── win32security.pyd
│   │   ├── win32service.pyd
│   │   ├── win32trace.pyd
│   │   ├── win32transaction.pyd
│   │   ├── win32ts.pyd
│   │   ├── win32wnet.pyd
│   │   └── winxpgui.py
│   ├── win32com/
│   │   ├── client/
│   │   │   ├── __init__.py
│   │   │   ├── build.py
│   │   │   ├── CLSIDToClass.py
│   │   │   ├── combrowse.py
│   │   │   ├── connect.py
│   │   │   ├── dynamic.py
│   │   │   ├── gencache.py
│   │   │   ├── genpy.py
│   │   │   ├── makepy.py
│   │   │   ├── selecttlb.py
│   │   │   ├── tlbrowse.py
│   │   │   └── util.py
│   │   ├── demos/
│   │   │   ├── __init__.py
│   │   │   ├── connect.py
│   │   │   ├── dump_clipboard.py
│   │   │   ├── eventsApartmentThreaded.py
│   │   │   ├── eventsFreeThreaded.py
│   │   │   ├── excelAddin.py
│   │   │   ├── excelRTDServer.py
│   │   │   ├── iebutton.py
│   │   │   ├── ietoolbar.py
│   │   │   ├── outlookAddin.py
│   │   │   └── trybag.py
│   │   ├── HTML/
│   │   │   ├── image/
│   │   │   ├── COM_Records.html
│   │   │   ├── docindex.html
│   │   │   ├── GeneratedSupport.html
│   │   │   ├── index.html
│   │   │   ├── misc.html
│   │   │   ├── package.html
│   │   │   ├── PythonCOM.html
│   │   │   ├── QuickStartClientCom.html
│   │   │   ├── QuickStartServerCom.html
│   │   │   └── variant.html
│   │   ├── include/
│   │   │   ├── PythonCOM.h
│   │   │   ├── PythonCOMRegister.h
│   │   │   └── PythonCOMServer.h
│   │   ├── libs/
│   │   │   ├── axscript.lib
│   │   │   └── pythoncom.lib
│   │   ├── makegw/
│   │   │   ├── __init__.py
│   │   │   ├── makegw.py
│   │   │   ├── makegwenum.py
│   │   │   └── makegwparse.py
│   │   ├── server/
│   │   │   ├── __init__.py
│   │   │   ├── connect.py
│   │   │   ├── dispatcher.py
│   │   │   ├── exception.py
│   │   │   ├── factory.py
│   │   │   ├── localserver.py
│   │   │   ├── policy.py
│   │   │   ├── register.py
│   │   │   └── util.py
│   │   ├── servers/
│   │   │   ├── __init__.py
│   │   │   ├── dictionary.py
│   │   │   ├── interp.py
│   │   │   ├── perfmon.py
│   │   │   ├── PythonTools.py
│   │   │   └── test_pycomtest.py
│   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   ├── daodump.py
│   │   │   ├── errorSemantics.py
│   │   │   ├── GenTestScripts.py
│   │   │   ├── pippo.idl
│   │   │   ├── pippo_server.py
│   │   │   ├── policySemantics.py
│   │   │   ├── readme.txt
│   │   │   ├── testAccess.py
│   │   │   ├── testADOEvents.py
│   │   │   ├── testall.py
│   │   │   ├── testArrays.py
│   │   │   ├── testAXScript.py
│   │   │   ├── testClipboard.py
│   │   │   ├── testCollections.py
│   │   │   ├── testConversionErrors.py
│   │   │   ├── testDates.py
│   │   │   ├── testDCOM.py
│   │   │   ├── testDictionary.py
│   │   │   ├── testDictionary.vbs
│   │   │   ├── testDynamic.py
│   │   │   ├── testExchange.py
│   │   │   ├── testExplorer.py
│   │   │   ├── testGatewayAddresses.py
│   │   │   ├── testGIT.py
│   │   │   ├── testInterp.vbs
│   │   │   ├── testIterators.py
│   │   │   ├── testmakepy.py
│   │   │   ├── testMarshal.py
│   │   │   ├── testMSOffice.py
│   │   │   ├── testMSOfficeEvents.py
│   │   │   ├── testPersist.py
│   │   │   ├── testPippo.py
│   │   │   ├── testPyComTest.py
│   │   │   ├── Testpys.sct
│   │   │   ├── testPyScriptlet.js
│   │   │   ├── testROT.py
│   │   │   ├── testServers.py
│   │   │   ├── testShell.py
│   │   │   ├── testStorage.py
│   │   │   ├── testStreams.py
│   │   │   ├── testvb.py
│   │   │   ├── testvbscript_regexp.py
│   │   │   ├── testWMI.py
│   │   │   ├── testxslt.js
│   │   │   ├── testxslt.py
│   │   │   ├── testxslt.xsl
│   │   │   └── util.py
│   │   ├── __init__.py
│   │   ├── License.txt
│   │   ├── olectl.py
│   │   ├── readme.html
│   │   ├── storagecon.py
│   │   ├── universal.py
│   │   └── util.py
│   ├── win32comext/
│   │   ├── adsi/
│   │   │   ├── demos/
│   │   │   ├── __init__.py
│   │   │   ├── adsi.pyd
│   │   │   └── adsicon.py
│   │   ├── authorization/
│   │   │   ├── demos/
│   │   │   ├── __init__.py
│   │   │   └── authorization.pyd
│   │   ├── axcontrol/
│   │   │   ├── __init__.py
│   │   │   └── axcontrol.pyd
│   │   ├── axdebug/
│   │   │   ├── __init__.py
│   │   │   ├── adb.py
│   │   │   ├── codecontainer.py
│   │   │   ├── contexts.py
│   │   │   ├── debugger.py
│   │   │   ├── documents.py
│   │   │   ├── dump.py
│   │   │   ├── expressions.py
│   │   │   ├── gateways.py
│   │   │   ├── stackframe.py
│   │   │   └── util.py
│   │   ├── axscript/
│   │   │   ├── client/
│   │   │   ├── Demos/
│   │   │   ├── server/
│   │   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   ├── asputil.py
│   │   │   └── axscript.pyd
│   │   ├── bits/
│   │   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   └── bits.pyd
│   │   ├── directsound/
│   │   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   └── directsound.pyd
│   │   ├── ifilter/
│   │   │   ├── demo/
│   │   │   ├── __init__.py
│   │   │   ├── ifilter.pyd
│   │   │   └── ifiltercon.py
│   │   ├── internet/
│   │   │   ├── __init__.py
│   │   │   ├── inetcon.py
│   │   │   └── internet.pyd
│   │   ├── mapi/
│   │   │   ├── demos/
│   │   │   ├── __init__.py
│   │   │   ├── emsabtags.py
│   │   │   ├── exchange.pyd
│   │   │   ├── mapi.pyd
│   │   │   ├── mapitags.py
│   │   │   └── mapiutil.py
│   │   ├── propsys/
│   │   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   ├── propsys.pyd
│   │   │   └── pscon.py
│   │   ├── shell/
│   │   │   ├── demos/
│   │   │   ├── test/
│   │   │   ├── __init__.py
│   │   │   ├── shell.pyd
│   │   │   └── shellcon.py
│   │   └── taskscheduler/
│   │       ├── test/
│   │       ├── __init__.py
│   │       └── taskscheduler.pyd
│   ├── win32ctypes/
│   │   ├── core/
│   │   │   ├── cffi/
│   │   │   ├── ctypes/
│   │   │   ├── __init__.py
│   │   │   ├── _winerrors.py
│   │   │   └── compat.py
│   │   ├── pywin32/
│   │   │   ├── __init__.py
│   │   │   ├── pywintypes.py
│   │   │   ├── win32api.py
│   │   │   └── win32cred.py
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_backends.py
│   │   │   ├── test_win32api.py
│   │   │   └── test_win32cred.py
│   │   ├── __init__.py
│   │   ├── pywintypes.py
│   │   ├── version.py
│   │   ├── win32api.py
│   │   └── win32cred.py
│   ├── yaml/
│   │   ├── __init__.py
│   │   ├── _yaml.cp314-win_amd64.pyd
│   │   ├── composer.py
│   │   ├── constructor.py
│   │   ├── cyaml.py
│   │   ├── dumper.py
│   │   ├── emitter.py
│   │   ├── error.py
│   │   ├── events.py
│   │   ├── loader.py
│   │   ├── nodes.py
│   │   ├── parser.py
│   │   ├── reader.py
│   │   ├── representer.py
│   │   ├── resolver.py
│   │   ├── scanner.py
│   │   ├── serializer.py
│   │   └── tokens.py
│   ├── zipp/
│   │   ├── compat/
│   │   │   ├── __init__.py
│   │   │   ├── overlay.py
│   │   │   ├── py310.py
│   │   │   └── py313.py
│   │   ├── __init__.py
│   │   ├── _functools.py
│   │   └── glob.py
│   ├── zipp-3.23.1.dist-info/
│   │   ├── licenses/
│   │   │   └── LICENSE
│   │   ├── INSTALLER
│   │   ├── METADATA
│   │   ├── RECORD
│   │   ├── top_level.txt
│   │   └── WHEEL
│   ├── _cffi_backend.cp314-win_amd64.pyd
│   ├── jsonref.py
│   ├── proxytypes.py
│   ├── pythoncom.py
│   ├── PyWin32.chm
│   ├── pywin32.pth
│   ├── pywin32.version.txt
│   └── typing_extensions.py
├── src/
│   └── ty_lsp/
│       ├── testmod/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── models.py
│       │   ├── service.py
│       │   └── utils.py
│       ├── __init__.py
│       ├── install.py
│       ├── lsp.py
│       └── server.py
├── .gitignore
├── CLAUDE.md
├── pyproject.toml
├── sample.py
├── SYSTEM_PROMPT.md
├── test_flow.py
├── ty_client.py
└── ty_server.py
```

### Project Stats

- **Python files**: 3481
- **JS/TS files**: 3
- **Total tracked files**: 3484

### Git Info

- **Branch**: `main`
  - c0a942f Fix: install python build module instead of only hatchling
  - ee6ff39 Initial commit: python-code-mcp server with ty LSP integration

### Git Status

```
  M CLAUDE.md
   M pyproject.toml
   M sample.py
   M src/ty_lsp/lsp.py
   M src/ty_lsp/server.py
  ?? Python314Libsite-packages/
  ?? SYSTEM_PROMPT.md
  ?? src/ty_lsp/install.py
  ?? src/ty_lsp/testmod/
```

---