# CLAUDE.md — Guía del proyecto

## Dependencias

Las dependencias están definidas en `pyproject.toml` con versiones exactas:

- **fastmcp** `3.2.4` — Framework para construir servidores MCP (Model Context Protocol)
- **ty** `0.0.33` — Type checker para Python, escrito en Rust por Astral

> **Nota:** Los hooks (`pre_tool_use.py`, `post_tool_use.py`) usan `httpx` en runtime, pero NO está declarado como dependencia. Los hooks hacen `sys.exit(0)` silencioso si `httpx` no está disponible.

## ty como servidor LSP

### Lanzamiento

```bash
ty server
```

- **Transporte:** stdio (stdin/stdout)
- **Lenguaje:** Python únicamente
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

- `callHierarchy/*`, `textDocument/codeLens`, `textDocument/documentColor`, `textDocument/documentLink`, `textDocument/implementation`, `typeHierarchy/*`

### Métodos delegados a Ruff

- `textDocument/formatting`, `textDocument/onTypeFormatting`, `textDocument/rangeFormatting`

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
python-code-mcp            → lanza el servidor MCP (HTTP en 127.0.0.1:8000)
python-code-mcp install    → registra el servidor en Claude Code y sale
```

### Módulos

| Archivo | Clase/Función | Descripción |
|---|---|---|
| `src/ty_lsp/server.py` | `mcp`, `FileError`, `main()` | Servidor FastMCP + entry point + rutas HTTP custom |
| `src/ty_lsp/lsp.py` | `TyServer` | Cliente LSP para ty (subprocess, JSON-RPC 2.0, framing Content-Length) |
| `src/ty_lsp/install.py` | `run_install()` | Lógica de instalación (`claude mcp add`) + registro de hooks |
| `src/ty_lsp/hooks/pre_tool_use.py` | — | Hook PreToolUse: envía POST a `/lsp/open` para calentar ty |
| `src/ty_lsp/hooks/post_tool_use.py` | — | Hook PostToolUse: consulta `/lsp/file-info` e imprime diagnósticos y símbolos |
| `src/ty_lsp/hooks/pre_tool_use_edit.py` | — | Hook PreToolUse Edit/Write: captura diagnósticos antes del cambio en snapshot temporal |
| `src/ty_lsp/hooks/post_tool_use_edit.py` | — | Hook PostToolUse Edit/Write: compara antes/después, muestra solo errores nuevos con remapeo de líneas |
| `src/ty_lsp/testmod/` | — | Módulo de prueba con imports cruzados para testing LSP multi-archivo |

### Entry point (`pyproject.toml`)

```toml
[project.scripts]
python-code-mcp = "ty_lsp.server:main"
```

Un solo entry point. `main()` revisa `sys.argv[1]` para decidir si instala o arranca el servidor.

### Estado global (`server.py`)

Variables globales usadas por las rutas HTTP custom (fuera del contexto MCP):

- `_ty_server: TyServer | None` — Referencia al servidor LSP activo
- `_open_files: dict[str, int]` — Dict de archivos abiertos en ty (URI → versión)

### Funciones auxiliares (`server.py`)

| Función | Descripción |
|---|---|
| `_parse_gitignore(root)` | Parsea `.gitignore` y retorna lista de `(pattern, is_negation)` |
| `_is_ignored(rel_path, patterns)` | Determina si un path relativo es ignorado por gitignore |
| `_open_project_files(ty, root)` | Abre todos los `.py` del proyecto en ty (respeta `.gitignore`) |
| `_ensure_file_open(ctx, file_path)` | Valida path y asegura que ty tenga el archivo abierto via didOpen |
| `_format_location(loc)` | Formatea una `Location` LSP (uri + range) como texto legible |
| `_extract_symbols(source)` | Extrae clases y funciones de código Python usando `ast` (2 niveles de profundidad) |

### Tools MCP expuestas (4 tools)

| Tool | Parámetros | Descripción |
|---|---|---|
| `hover` | `file_path`, `line`, `character` | Info de tipo inferido para un símbolo |
| `type_check` | `file_path` | Diagnósticos de tipo para un archivo |
| `find_definition` | `file_path`, `line`, `col` | Ubicación de la definición de un símbolo |
| `find_references` | `file_path`, `line`, `col` | Todas las referencias a un símbolo en el workspace |

> **Nota:** `rename_symbol` está **desactivada**. El rename de ty es textual (no semántico) y puede corromper archivos sin relación con el símbolo renombrado.

### Rutas HTTP personalizadas

Además de las tools MCP, el servidor expone tres endpoints HTTP para los hooks:

| Ruta | Método | Descripción |
|---|---|---|
| `/lsp/open` | POST | Abre un `.py` en ty (calentamiento para hook PreToolUse) |
| `/lsp/file-info` | POST | Retorna diagnósticos de tipo y símbolos AST para un `.py` |
| `/lsp/reload` | POST | Recarga un `.py` en ty post-edición (didChange + didOpen fallback) |

Ambas rutas usan las variables globales `_ty_server` y `_open_files` (no el contexto lifespan, ya que son endpoints HTTP fuera del contexto MCP tool).

### Sistema de Hooks

Los hooks se instalan durante `python-code-mcp install` y se integran con Claude Code:

**Hooks para Read:**

1. **PreToolUse** (`pre_tool_use.py`): Al leer un `.py`, envía POST a `/lsp/open` para precargar el archivo en ty (timeout 3s)
2. **PostToolUse** (`post_tool_use.py`): Tras leer un `.py`, consulta `/lsp/file-info` e imprime símbolos y diagnósticos como contexto adicional para Claude (timeout 10s)

**Hooks para Edit/Write:**

3. **PreToolUse** (`pre_tool_use_edit.py`): Antes de editar/escribir un `.py`, captura diagnósticos actuales y contenido del archivo en un snapshot temporal (`$TEMP/ty-edit-{sha256[:16]}.json`). No imprime nada (silencioso).
4. **PostToolUse** (`post_tool_use_edit.py`): Tras editar/escribir un `.py`, recarga el archivo en ty via `/lsp/reload`, compara diagnósticos antes/después con remapeo de líneas, y muestra solo los errores NUEVOS introducidos por el cambio. También muestra errores resueltos.

### Remapeo de líneas (Edit)

El post-hook de Edit calcula el offset de líneas para comparar diagnósticos:
- `start_line` = línea donde empieza `old_string` en el contenido pre-edit
- `old_count` = líneas del `old_string`
- `delta` = `new_string.lines - old_string.lines`
- Diagnósticos "before" con `line > start_line + old_count` se ajustan: `line += delta`
- Para Write: no hay remapeo (archivo completamente nuevo)

Archivos instalados:
- `~/.claude/hooks/python-code-mcp-pre.py` (matcher: `Read`)
- `~/.claude/hooks/python-code-mcp-post.py` (matcher: `Read`)
- `~/.claude/hooks/python-code-mcp-pre-edit.py` (matcher: `Edit|Write`)
- `~/.claude/hooks/python-code-mcp-post-edit.py` (matcher: `Edit|Write`)

### Lifespan

El lifespan `ty_lifespan` ejecuta al inicio:

1. Crea un `TyServer`, lo inicia y lo inicializa con el `rootUri` del `cwd`
2. Precarga todos los archivos `.py` del proyecto via `didOpen` (respeta `.gitignore`)
3. Setea las variables globales `_ty_server` y `_open_files`
4. Yield de `{"ty": TyServer, "open_files": set[str]}`
5. Al shutdown: detiene el subprocess de ty, limpia las variables globales

### Flujo: `server.py` → `lsp.py`

1. `main()` → `mcp.run(transport="http")` arranca FastMCP en HTTP (127.0.0.1:8000)
2. El lifespan `ty_lifespan` crea un `TyServer`, lo inicia, lo inicializa y precarga los `.py`
3. Las tools usan `_ensure_file_open()` para validar el path y abrir archivos bajo demanda
4. Las tools acceden al `TyServer` vía `ctx.lifespan_context["ty"]`
5. Las rutas HTTP custom acceden al `TyServer` vía la variable global `_ty_server`
6. `TyServer` maneja toda la comunicación LSP con ty via subprocess (stdin/stdout)

### Instalación (`install.py`)

El comando `python-code-mcp install` ejecuta:

1. Busca `claude` CLI en PATH (`shutil.which`)
2. Registra el servidor: `claude mcp add -s user -t http python-code-mcp http://127.0.0.1:8000/mcp`
3. Copia 4 hooks a `~/.claude/hooks/` (prefijo `python-code-mcp-`)
4. Actualiza `~/.claude/settings.json` con 4 entradas de hooks (2 Read + 2 Edit|Write), preservando hooks existentes

## TyServer — Cliente LSP para ty

### Implementación

`src/ty_lsp/lsp.py` contiene la clase `TyServer` que maneja toda la comunicación con `ty server` via subprocess:

- **Transporte:** stdio (stdin/stdout) con framing LSP (`Content-Length`)
- **Protocolo:** JSON-RPC 2.0
- **Métodos de bajo nivel:** `start()`, `send()`, `send_request()`, `send_notification()`, `send_and_wait()`, `read_message()`, `stop()`
- **Métodos de alto nivel (LSP):** `initialize()`, `open_file()`, `change_file()`, `close_file()`, `hover()`, `diagnostic()`, `definition()`, `references()`, `rename()`

### Flujo LSP: didOpen → hover

1. `initialize(root_uri)` — handshake: `initialize` request + `initialized` notificación
2. `open_file(file_uri, content, version=1)` — notificación `textDocument/didOpen` (uri via `Path.as_uri()`, languageId `"python"`)
3. `hover(file_uri, line, character)` — request `textDocument/hover`, posiciones 0-indexed

**Notas clave:**
- Un archivo debe estar "abierto" (didOpen) antes de consultar hover/diagnostic/definition
- ty envía `publishDiagnostics` como push tras didOpen; `send_and_wait` las descarta automáticamente
- Para actualizar contenido: `didChange` o didOpen con nueva versión
