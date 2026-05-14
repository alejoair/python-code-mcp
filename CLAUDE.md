# CLAUDE.md — Guía del proyecto

## Dependencias

Las dependencias están definidas en `pyproject.toml` con versiones exactas:

- **fastmcp** `3.2.4` — Framework para construir servidores MCP (Model Context Protocol)
- **httpx** `>=0.27` — Cliente HTTP asíncrono, usado por los hooks para comunicarse con el servidor MCP
- **tree-sitter-language-pack** `1.8.0` — Gramáticas pre-compiladas de tree-sitter para 305 lenguajes
- **tree-sitter** `>=0.24,<1` — Core bindings para parser tree-sitter (Parser, Node, Query, Tree)
- **tree-sitter-python** `>=0.24,<1` — Gramática Python para tree-sitter
- **grep-ast** `0.9.0` — Extracción de contexto sintáctico para búsqueda de código (usado por `tools_search.py`)
- **ty** `0.0.33` — Type checker para Python, escrito en Rust por Astral

> **Nota:** Los hooks hacen `sys.exit(0)` silencioso si `httpx` no está disponible.

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
| `src/ty_lsp/app.py` | `mcp`, `ty_server`, `open_files`, `ts_index` | Instancia FastMCP central + estado global mutable |
| `src/ty_lsp/server.py` | `ty_lifespan()`, `main()` | Entry point + lifespan (imports con side-effects de tools y routes) |
| `src/ty_lsp/lsp.py` | `TyServer` | Cliente LSP para ty (subprocess, JSON-RPC 2.0, framing Content-Length) |
| `src/ty_lsp/treesitter.py` | `TreeSitterIndex` | Índice de proyecto tree-sitter, funciones de extracción estructural |
| `src/ty_lsp/validation.py` | `FileError`, `validate_py_file()`, `ensure_file_open()`, `open_project_files()` | Validación de archivos y gestión de apertura en ty |
| `src/ty_lsp/gitignore.py` | `parse_gitignore()`, `is_ignored()` | Parseo y evaluación de `.gitignore` |
| `src/ty_lsp/lsp_helpers.py` | `format_location()`, `uri_to_path()` | Formateo de respuestas LSP (Location → texto legible, URI → path) |
| `src/ty_lsp/ast_extract.py` | `extract_symbols()` | Extracción de símbolos con `ast` (clases y funciones, 2 niveles) |
| `src/ty_lsp/routes.py` | — | Rutas HTTP custom (`/lsp/open`, `/lsp/file-info`, `/lsp/reload`, `/lsp/workspace-diff`) |
| `src/ty_lsp/tools_lsp.py` | — | Tools MCP semánticas (ty LSP): `hover`, `type_check`, `workspace_check`, `find_definition`, `find_references`, `restart_servers` |
| `src/ty_lsp/tools_treesitter.py` | — | Tools MCP estructurales (tree-sitter): `list_symbols`, `get_function_body`, `get_class_skeleton`, `extract_enclosing_unit` |
| `src/ty_lsp/tools_search.py` | `PyTreeContext`, `search_code()` | Tool MCP de búsqueda con contexto sintáctico (grep-ast + tree-sitter) |
| `src/ty_lsp/install.py` | `run_install()`, `find_claude_cli()` | Lógica de instalación (`claude mcp add`) + registro de hooks |
| `src/ty_lsp/hooks/pre_tool_use.py` | — | Hook PreToolUse: envía POST a `/lsp/open` para calentar ty |
| `src/ty_lsp/hooks/post_tool_use.py` | — | Hook PostToolUse: consulta `/lsp/file-info` e imprime diagnósticos y símbolos |
| `src/ty_lsp/hooks/pre_tool_use_edit.py` | — | Hook PreToolUse Edit/Write: captura diagnósticos + workspace diagnostics en snapshot temporal |
| `src/ty_lsp/hooks/post_tool_use_edit.py` | — | Hook PostToolUse Edit/Write: compara antes/después con remapeo de líneas + impacto cross-file + bloqueo configurable |
| `src/ty_lsp/hooks/hook_config.py` | `HookConfig` | Lectura de configuración de bloqueo desde `[tool.python-code-mcp.hooks]` en pyproject.toml |
| `src/ty_lsp/testmod/` | — | Módulo de prueba con imports cruzados para testing LSP multi-archivo |

### Entry point (`pyproject.toml`)

```toml
[project.scripts]
python-code-mcp = "ty_lsp.server:main"
```

Un solo entry point. `main()` revisa `sys.argv[1]` para decidir si instala o arranca el servidor.

### Estado global (`app.py`)

Variables globales usadas por las rutas HTTP custom (fuera del contexto MCP):

- `ty_server: TyServer | None` — Referencia al servidor LSP activo
- `open_files: dict[str, int]` — Dict de archivos abiertos en ty (URI → versión)
- `ts_index: TreeSitterIndex | None` — Índice tree-sitter del proyecto

El lifespan en `server.py` setea estas variables al inicio y las limpia al shutdown.

### Tools MCP expuestas (10 tools)

**Tools semánticas (ty LSP):**

| Tool | Parámetros | Descripción |
|---|---|---|
| `hover` | `file_path`, `line`, `character` | Info de tipo inferido para un símbolo. Línea 1-indexed, columna 0-indexed. |
| `type_check` | `file_path` | Diagnósticos de tipo para un archivo |
| `workspace_check` | — | Diagnósticos de todo el workspace usando inferencia de módulo completo de ty |
| `find_definition` | `file_path`, `line`, `col` | Ubicación de la definición de un símbolo. Línea 1-indexed. |
| `find_references` | `file_path`, `line`, `col` | Todas las referencias a un símbolo en el workspace. Línea 1-indexed. |
| `restart_servers` | — | Reinicia ty + ruff LSP servers para recargar config de pyproject.toml sin reiniciar el MCP server. |

> **Nota:** Las tools `hover`, `find_definition` y `find_references` usan tree-sitter (`find_identifier_at`) para corregir posiciones imprecisas automáticamente — si no hay info en la posición exacta, buscan el identifier más cercano y reintentan.

> **Nota:** `rename_symbol` está **desactivada**. El rename de ty es textual (no semántico) y puede corromper archivos sin relación con el símbolo renombrado.

**Tools estructurales (tree-sitter):**

| Tool | Parámetros | Descripción |
|---|---|---|
| `list_symbols` | `file_path`, `kind?` | Outline de un archivo: clases, métodos, funciones con números de línea. Filtrable por kind: `class`, `function`, `method`. |
| `get_function_body` | `file_path`, `function_name`, `class_name?` | Código fuente exacto de una función o método (con decorators y docstring) |
| `get_class_skeleton` | `file_path`, `class_name` | Estructura de una clase: bases, firmas de métodos, decorators, docstrings. Sin bodies. |
| `extract_enclosing_unit` | `file_path`, `line` | Unidad mínima que contiene una línea (función, clase). Línea 1-indexed. |

**Tool de búsqueda:**

| Tool | Parámetros | Descripción |
|---|---|---|
| `search_code` | `pattern`, `file_path?`, `regex?`, `ignore_case?`, `max_results?` | Busca patrón (literal o regex) en archivos Python del workspace. Retorna matches con contexto sintáctico (función/clase enclosing). |

### Rutas HTTP personalizadas

Además de las tools MCP, el servidor expone cuatro endpoints HTTP para los hooks:

| Ruta | Método | Descripción |
|---|---|---|
| `/lsp/open` | POST | Abre un `.py` en ty (calentamiento para hook PreToolUse) |
| `/lsp/file-info` | POST | Retorna diagnósticos de tipo y símbolos AST para un `.py` |
| `/lsp/reload` | POST | Recarga un `.py` en ty post-edición (didChange + didOpen fallback) |
| `/lsp/check-hypothetical` | POST | Diagnostica contenido simulado sin persistirlo (didChange + diagnostic + restaurar). Usado por pre-hook para bloqueo preventivo. |
| `/lsp/workspace-diff` | POST | Diagnósticos de todos los archivos abiertos agrupados por URI (pull model) |

Las rutas importan `ty_server`, `open_files` y `ts_index` desde `app.py` (no usan el contexto lifespan, ya que son endpoints HTTP fuera del contexto MCP tool).

### Sistema de Hooks

Los hooks se instalan durante `python-code-mcp install` y se integran con Claude Code:

**Hooks para Read:**

1. **PreToolUse** (`pre_tool_use.py`): Al leer un `.py`, envía POST a `/lsp/open` para precargar el archivo en ty (timeout 3s)
2. **PostToolUse** (`post_tool_use.py`): Tras leer un `.py`, consulta `/lsp/file-info` y devuelve símbolos y diagnósticos como contexto adicional para Claude via `hookSpecificOutput.additionalContext` (JSON) (timeout 10s)

**Hooks para Edit/Write:**

3. **PreToolUse** (`pre_tool_use_edit.py`): Antes de editar/escribir un `.py`, captura diagnósticos actuales y contenido en un snapshot temporal. Si el bloqueo está activo (`block-mode != "off"`), simula el cambio (`before_content.replace(old_string, new_string)` para Edit, `content` para Write), lo envía a ty via `/lsp/check-hypothetical`, compara diagnósticos antes/después, y si hay errores nuevos que coinciden con la configuración → retorna `{"decision": "block", "reason": "..."}` para **prevenir** que el cambio se aplique. Si no hay bloqueo o no hay errores → silencioso (no imprime nada).
4. **PostToolUse** (`post_tool_use_edit.py`): Tras editar/escribir un `.py`, recarga el archivo en ty via `/lsp/reload`, compara diagnósticos antes/después con remapeo de líneas, y muestra solo los errores NUEVOS introducidos por el cambio via `hookSpecificOutput.additionalContext` (JSON). También muestra errores resueltos y realiza análisis de impacto cross-file. Es puramente informativo — nunca bloquea.

### Remapeo de líneas (Edit)

El post-hook de Edit calcula el offset de líneas para comparar diagnósticos:
- `start_line` = línea donde empieza `old_string` en el contenido pre-edit
- `old_count` = líneas del `old_string`
- `delta` = `new_string.lines - old_string.lines`
- Diagnósticos "before" con `line > start_line + old_count` se ajustan: `line += delta`
- Para Write: no hay remapeo (archivo completamente nuevo)

### Configuración de bloqueo de Hooks

Los hooks de Edit/Write pueden **bloquear** cambios que introduzcan errores nuevos, según la configuración en `[tool.python-code-mcp.hooks]` en `pyproject.toml`:

```toml
[tool.python-code-mcp.hooks]
block-mode = "off"          # "off" | "ty" | "ruff" | "all"
block-severity = 1           # 1=Error, 2=Warning, 3=Info
block-rules = []             # Whitelist de códigos. Vacío = todas.
block-cross-file = true      # Incluir impacto cross-file
```

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `block-mode` | `string` | `"off"` | `"off"` = solo reportar, `"ty"` = bloquear por type errors, `"ruff"` = bloquear por lint errors, `"all"` = ambos |
| `block-severity` | `int` | `1` | Severidad mínima para bloquear: `1`=Error, `2`=Warning, `3`=Info |
| `block-rules` | `list[string]` | `[]` | Lista blanca de códigos de regla que bloquean. Vacío = todas las reglas con severidad suficiente bloquean. Ejemplos ty: `"unresolved-import"`, `"invalid-assignment"`. Ejemplos ruff: `"F401"`, `"F841"`. |
| `block-cross-file` | `bool` | `true` | Incluir errores nuevos en otros archivos del workspace como razón de bloqueo |

**Flujo de bloqueo (en el PRE-hook):**

1. El pre-hook (`pre_tool_use_edit.py`) lee la config de `[tool.python-code-mcp.hooks]`.
2. Si `block-mode != "off"`: simula el cambio en memoria, lo envía a `/lsp/check-hypothetical`.
3. Compara diagnósticos del contenido hipotético vs diagnósticos actuales del archivo.
4. Filtra los errores nuevos con `HookConfig.filter_blocking()`.
5. Si hay errores que bloquean → retorna `{"decision": "block", "reason": "..."}` y Claude **nunca aplica** el cambio.
6. Si no hay errores que bloquean → el cambio procede normalmente, y el post-hook reporta info adicional.

**Ejemplo: bloquear solo imports no resueltos y variables no usadas:**

```toml
[tool.python-code-mcp.hooks]
block-mode = "all"
block-severity = 1
block-rules = ["unresolved-import", "unresolved-reference", "F401", "F841"]
block-cross-file = true
```

Archivos instalados:
- `.claude/hooks/python-code-mcp-pre.py` (matcher: `Read`)
- `.claude/hooks/python-code-mcp-post.py` (matcher: `Read`)
- `.claude/hooks/python-code-mcp-pre-edit.py` (matcher: `Edit|Write`)
- `.claude/hooks/python-code-mcp-post-edit.py` (matcher: `Edit|Write`)

### Lifespan

El lifespan `ty_lifespan` (en `server.py`) ejecuta al inicio:

1. Parsea `.gitignore` una vez via `gitignore.parse_gitignore()` (patterns reutilizados)
2. Crea un `TyServer`, lo inicia y lo inicializa con el `rootUri` del `cwd`
3. Precarga todos los archivos `.py` del proyecto via `validation.open_project_files()` (respeta `.gitignore`)
4. Construye el índice tree-sitter (`TreeSitterIndex.build()`) sobre los mismos archivos
5. Setea las variables globales en `app.py`: `app.ty_server`, `app.open_files`, `app.ts_index`
6. Yield de `{"ty": TyServer, "open_files": dict[str, int], "ts_index": TreeSitterIndex}`
7. Al shutdown: detiene el subprocess de ty, limpia las variables globales en `app.py`

### Flujo: `server.py` → `lsp.py`

1. `main()` → `mcp.run(transport="http")` arranca FastMCP en HTTP (127.0.0.1:8000)
2. El lifespan `ty_lifespan` crea un `TyServer`, lo inicia, lo inicializa y precarga los `.py`
3. Los módulos `tools_lsp`, `tools_treesitter`, `tools_search` y `routes` se importan en `server.py` — sus decoradores `@mcp.tool` y `@mcp.custom_route` se registran como side-effect
4. Las tools usan `validation.ensure_file_open()` para validar el path y abrir archivos bajo demanda
5. Las tools acceden al `TyServer` vía `ctx.lifespan_context["ty"]`
6. Las rutas HTTP custom acceden al `TyServer` vía `app.ty_server`
7. `/lsp/reload` también actualiza el índice tree-sitter via `app.ts_index.reindex_file()`
8. `TyServer` maneja toda la comunicación LSP con ty via subprocess (stdin/stdout)

### Instalación (`install.py`)

El comando `python-code-mcp install` ejecuta:

1. Busca `claude` CLI en PATH (`shutil.which`)
2. Registra el servidor: `claude mcp add -s project -t http python-code-mcp http://127.0.0.1:8000/mcp`
3. Copia 4 hooks a `.claude/hooks/` del proyecto (prefijo `python-code-mcp-`)
4. Actualiza `.claude/settings.json` del proyecto con 4 entradas de hooks (2 Read + 2 Edit|Write), preservando hooks existentes

## TreeSitterIndex — Índice estructural tree-sitter

### Implementación

`src/ty_lsp/treesitter.py` contiene la clase `TreeSitterIndex` y funciones de extracción:

- **Parser:** `tree_sitter.Parser` con gramática Python, cached como singleton via `_get_parser()`
- **APIs:** `tree-sitter-language-pack` (`process()`) para outline, `tree-sitter` de bajo nivel para extracción quirúrgica
- **Índice:** `dict[str, list[SymbolLocation]]` — mapa nombre → ubicaciones, lookup O(1)
- **Cache:** `dict[str, tree_sitter.Tree]` — árboles parseados cacheados por path

### Funciones de extracción

| Función | Descripción |
|---|---|
| `list_file_symbols(file_path, kind_filter?)` | Outline vía `process()` API de alto nivel |
| `extract_function_body(file_path, name, class_name?)` | Código fuente exacto de una función via byte offsets |
| `extract_class_skeleton(file_path, name)` | Estructura de clase: bases, firmas, docstrings, sin bodies |
| `extract_enclosing(file_path, line)` | Unidad mínima que contiene una línea (0-indexed) |
| `find_identifier_at(file_path, line, col)` | Encuentra el identifier más cercano a una posición (0-indexed) |

### Posicionamiento

- **Tools MCP:** `line` es **1-indexed** (natural para el LLM), `character`/`col` es **0-indexed** (estándar LSP)
- **Interno (tree-sitter, ty):** todo **0-indexed** — las tools convierten antes de llamar
- **Corrección automática:** `hover`, `find_definition`, `find_references` usan `find_identifier_at` para ajustar posiciones imprecisas

## TyServer — Cliente LSP para ty

### Implementación

`src/ty_lsp/lsp.py` contiene la clase `TyServer` que maneja toda la comunicación con `ty server` via subprocess:

- **Transporte:** stdio (stdin/stdout) con framing LSP (`Content-Length`)
- **Protocolo:** JSON-RPC 2.0
- **Métodos de bajo nivel:** `start()`, `send()`, `send_request()`, `send_notification()`, `send_and_wait()`, `read_message()`, `stop()`
- **Métodos de alto nivel (LSP):** `initialize()`, `open_file()`, `change_file()`, `close_file()`, `hover()`, `diagnostic()`, `workspace_diagnostic()`, `definition()`, `references()`, `rename()`

### Flujo LSP: didOpen → hover

1. `initialize(root_uri)` — handshake: `initialize` request + `initialized` notificación
2. `open_file(file_uri, content, version=1)` — notificación `textDocument/didOpen` (uri via `Path.as_uri()`, languageId `"python"`)
3. `hover(file_uri, line, character)` — request `textDocument/hover`, posiciones 0-indexed

**Notas clave:**
- Un archivo debe estar "abierto" (didOpen) antes de consultar hover/diagnostic/definition
- ty envía `publishDiagnostics` como push tras didOpen; `send_and_wait` las descarta automáticamente
- Para actualizar contenido: `didChange` o didOpen con nueva versión
- `workspace_diagnostic()` recolecta diagnósticos push de todo el workspace (drain de hasta 500 mensajes con timeout de 5s cada uno)

## Project Context (Auto-generated)

> **Nota**: Esta sección se genera automáticamente antes de cada query.
> No la edites manualmente ya que se sobrescribirá.
>
> Providers activos: generate_system_context, generate_extended_system_context, generate_filetree_context, generate_stats_context, generate_git_context, generate_git_status_context

### System Info

- **OS**: 🪟 Windows 11 (AMD64)
- **User**: `alejandro.cuartas@CO-IT026150`
- **Home**: `C:\Users\alejandro.cuartas`
- **Shell**: `C:\WINDOWS\system32\cmd.exe`
- **Python**: `3.12.0` → `C:\Users\alejandro.cuartas\AppData\Local\Programs\Python\Python312\python.exe`
- **Date/Time**: 2026-05-14 09:28:21 (SA Pacific Standard Time)
- **Unix Timestamp**: `1778768901`



### Extended System Info

- **LANG**: `unknown`
- **TERM**: `unknown`
- **PATH**:
  ```
  C:\windows\system32;C:\windows;C:\windows\System32\Wbem;C:\windows\System32\WindowsPowerShell\v1.0\;C:\windows\System32\OpenSSH\;
  ... C:\Users\alejandro.cuartas\AppData\Local\Globant\Coda\CodingAgent\bin;C:\Users\alejandro.cuartas\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe;
  ```



### File Tree

```
python-code-mcp/
├── .github/
│   └── workflows/
│       └── publish.yml
├── src/
│   └── ty_lsp/
│       ├── hooks/
│       │   ├── __init__.py
│       │   ├── hook_config.py
│       │   ├── post_tool_use.py
│       │   ├── post_tool_use_edit.py
│       │   ├── pre_tool_use.py
│       │   └── pre_tool_use_edit.py
│       ├── testmod/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── models.py
│       │   ├── service.py
│       │   └── utils.py
│       ├── __init__.py
│       ├── app.py
│       ├── ast_extract.py
│       ├── gitignore.py
│       ├── install.py
│       ├── lsp.py
│       ├── lsp_helpers.py
│       ├── routes.py
│       ├── server.py
│       ├── tools_lsp.py
│       ├── tools_ruff.py
│       ├── tools_search.py
│       ├── tools_treesitter.py
│       ├── treesitter.py
│       └── validation.py
├── .gitignore
├── CLAUDE.md
├── pyproject.toml
├── sample.py
├── SYSTEM_PROMPT.md
├── test_flow.py
├── test_hook.py
├── ty_client.py
└── ty_server.py
```

### Project Stats

- **Python files**: 35
- **JS/TS files**: 0
- **Total tracked files**: 35

### Git Info

- **Branch**: `main`
  - f54e522 Add Ruff LSP integration for linting, formatting, and code actions
  - 611b65c Refactor into modular architecture and update CLAUDE.md
  - 7029efb Add workspace-level diagnostics with cross-file impact detection

### Git Status

```
  M .mcp.json
   M CLAUDE.md
   M pyproject.toml
   M src/ty_lsp/app.py
   M src/ty_lsp/hooks/post_tool_use_edit.py
   M src/ty_lsp/hooks/pre_tool_use_edit.py
   M src/ty_lsp/routes.py
   M src/ty_lsp/server.py
   M src/ty_lsp/tools_lsp.py
  ?? src/ty_lsp/hooks/hook_config.py
```

---