# obsidian-mcp-opencode

Python MCP server for Obsidian vaults. Cross-CLI compatible with OpenCode, Claude Code, Gemini CLI, Cursor, and any other MCP-compliant client. It wraps the [Obsidian Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin with hard-coded safety rules.

![Python >=3.11](https://img.shields.io/badge/python-%3E%3D3.11-blue)
![License Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)
![MCP compliant](https://img.shields.io/badge/MCP-compliant-purple)

## Two Workflow Modes

| Mode | Tools | Use case |
|---|---:|---|
| **`generic`** (default) | 5–6 | Any Obsidian vault. Permissive Markdown whitelist. |
| **`freya`** (opt-in) | 10–11 | Adopters of the [Freya workflow](#adopting-freya-mode). Strict project-pattern whitelist. |

`generic` is the default when nothing is specified. Switch modes with either:

- `OBSIDIAN_WORKFLOW=freya` in your env file, or
- `--workflow freya` in the MCP server command.

The optional extra tool is `move_note`, which is only registered when you add `--allow-move`.

## Tools

### Core tools available in both modes

- `read_note(path)` — read a vault file
- `write_note(path, content, overwrite=false)` — create a new file or replace an existing one
- `append_note(path, content)` — append to an existing file or create it if the parent directory exists
- `list_notes(path="", recursive=false)` — list folder contents
- `search_vault(query, path_prefix="", max_results=50)` — substring search across file names and content

### Freya-only tools

- `get_mistake_log()` — read the structured Freya mistake log
- `append_mistake_log(...)` — append a validated 5-field mistake entry
- `get_pipeline_index()` — read the cross-project reuse index
- `search_projects(query)` — search only inside `Projects/`
- `bootstrap_project(slug, files)` — create a new `Projects/{slug}/` folder and starter files

### Optional tool in both modes

- `move_note(source_path, destination_path)` — move or rename a note

This tool is off by default. To enable it, start the server with `--allow-move`.

## Quick Start (Generic Mode)

Throughout this README, replace `<python>` with the absolute path to your Python interpreter, for example `/usr/bin/python3`, `~/.pyenv/shims/python`, or `~/miniconda/bin/python`. Do not rely on shell aliases.

### 1. Install the Obsidian plugin

Install [Obsidian Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin version 4.0.0 or newer.

In plugin settings:

- enable **Non-encrypted (HTTP) Server** if you want to use port `27123`, or
- use the HTTPS port `27124` if you prefer TLS.

Then generate an API key and keep it ready.

### 2. Clone and install this package

```bash
git clone https://github.com/ibanunmangun/obsidian-mcp.git
cd obsidian-mcp
<python> -m pip install -e .[dev]
```

### 3. Create the env file

```bash
mkdir -p ~/.config/obsidian-mcp-opencode
cp configs/.env.example ~/.config/obsidian-mcp-opencode/.env
```

Edit `~/.config/obsidian-mcp-opencode/.env` and set at least:

```env
OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
OBSIDIAN_API_KEY=your-local-rest-api-bearer-token
```

If you do nothing else, the server runs in `generic` mode.

### 4. Add the MCP server to your AI client

#### OpenCode

Example `~/.config/opencode/opencode.json` entry:

```json
{
  "mcp": {
    "obsidian": {
      "type": "local",
      "command": [
        "<python>",
        "-m",
        "obsidian_mcp_opencode"
      ],
      "enabled": true
    }
  }
}
```

#### Claude Code

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "<python>",
      "args": ["-m", "obsidian_mcp_opencode"]
    }
  }
}
```

#### Gemini CLI

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "<python>",
      "args": ["-m", "obsidian_mcp_opencode"]
    }
  }
}
```

#### Cursor

Cursor MCP setup changes over time, but the command shape is the same: point Cursor to an MCP server process that runs:

```bash
<python> -m obsidian_mcp_opencode
```

If your Cursor version uses a JSON config, use the same `command` + `args` structure as Claude Code.

### 5. Restart your client and verify

After editing MCP settings, restart the CLI or editor session and call:

- `list_notes(path="")`

If you see the core tools and root vault listing, setup is working.

## Adopting Freya Mode

The Freya workflow is a structured project-memory convention used by an AI agent named Freya. It assumes a specific vault layout and stricter rules than generic mode.

```text
your-vault/
├── Freya - Mistake Log.md
├── LOGS.md
└── Projects/
    ├── PIPELINE_INDEX.md
    └── {project-slug}/
        ├── PROJECT.md
        ├── LOGS.md
        ├── PRD.md
        ├── PREMORTEM.md
        ├── DESIGN.md
        └── ...
```

If your vault does not follow that structure, stay on `generic` mode.

If you want Freya mode:

1. Set this in `~/.config/obsidian-mcp-opencode/.env`:
   ```env
   OBSIDIAN_WORKFLOW=freya
   ```
2. Restart your MCP client.
3. The five Freya-specific tools appear automatically.

What those tools are for:

- `get_mistake_log` and `append_mistake_log` protect a shared mistake log from accidental overwrite.
- `get_pipeline_index` gives the agent a reusable pattern catalog across projects.
- `search_projects` narrows search to project notes only.
- `bootstrap_project` is the only supported way to create a new project folder in that convention.

## Configuration

| Env var | Default | Description |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | required | Absolute path to your vault |
| `OBSIDIAN_API_KEY` | required | Bearer token from the Local REST API plugin |
| `OBSIDIAN_BASE_URL` | `http://127.0.0.1:27123` | Plugin URL. Use `https://127.0.0.1:27124` for HTTPS |
| `OBSIDIAN_WORKFLOW` | `generic` | `generic` or `freya` |
| `OBSIDIAN_WRITE_PATTERNS` | mode-dependent | Comma-separated write pattern override |
| `OBSIDIAN_APPEND_ONLY_PATTERNS` | mode-dependent | Comma-separated append-only pattern override |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

### Default patterns by mode

- `generic`
  - write whitelist: `*.md`, `**/*.md`
  - append-only: none
- `freya`
  - write whitelist: strict `Projects/{slug}/...` patterns plus `Freya - Mistake Log.md` and root `LOGS.md`
  - append-only: mistake log, root `LOGS.md`, and project log files

### CLI flags

- `--workflow {generic,freya}` — override env workflow
- `--read-only` — disable write tools
- `--allow-move` — enable `move_note`
- `--env-file PATH` — override default env-file lookup

## Cross-CLI Setup Notes

The most important rule across all clients is: use an absolute Python interpreter path.

Examples:

```bash
/usr/bin/python3 -m obsidian_mcp_opencode
~/miniconda/bin/python -m obsidian_mcp_opencode
~/.pyenv/shims/python -m obsidian_mcp_opencode
```

If you want Freya mode explicitly from the command line instead of the env file:

```bash
<python> -m obsidian_mcp_opencode --workflow freya
```

If you want rename/move support too:

```bash
<python> -m obsidian_mcp_opencode --allow-move
```

Or both:

```bash
<python> -m obsidian_mcp_opencode --workflow freya --allow-move
```

## For LLM Agents Helping a User Set This Up

If you are an AI agent and a user asks you to install this MCP server, follow this checklist.

### 1. Check prerequisites

Verify that the user has:

- Obsidian installed
- the Local REST API plugin installed and enabled
- plugin version `4.0.0+`
- HTTP or HTTPS server enabled in plugin settings
- a generated API key

If the plugin is missing, tell them to open Community Plugins and install **Local REST API**.

### 2. Detect the right workflow mode

With the user's permission, inspect the vault structure.

Suggest **Freya mode** only if you see signals like:

- `Freya - Mistake Log.md`
- `Projects/PIPELINE_INDEX.md`
- `Projects/{slug}/PROJECT.md`
- append-only session logs under project folders

Otherwise, default to **Generic mode**.

If the vault is ambiguous, ask before choosing.

### 3. Install the package

```bash
git clone https://github.com/ibanunmangun/obsidian-mcp.git
cd obsidian-mcp
<python> -m pip install -e .[dev]
```

### 4. Create the env file

Place it at:

```text
~/.config/obsidian-mcp-opencode/.env
```

Required:

```env
OBSIDIAN_VAULT_PATH=/absolute/path/to/vault
OBSIDIAN_API_KEY=token
```

Optional if Freya workflow was detected:

```env
OBSIDIAN_WORKFLOW=freya
```

### 5. Wire the MCP client

Identify the actual client first:

- OpenCode
- Claude Code
- Gemini CLI
- Cursor
- another MCP-compatible host

Then add the server command using the user's absolute interpreter path.

If they want rename or move support, include `--allow-move`.

### 6. Verify setup

Ask the user to restart their client and run:

- `list_notes(path="")`

Expected result:

- in generic mode: 5 core tools, or 6 if `move_note` is enabled
- in Freya mode: 10 tools, or 11 if `move_note` is enabled

### 7. Common errors and fixes

- `api_unreachable`
  - Obsidian is closed, plugin server is off, or wrong port/base URL
- `api_unauthorized`
  - API key is wrong, expired, or copied incorrectly
- `path_forbidden`
  - path is outside the vault, contains forbidden segments, or fails the active whitelist
- `parent_directory_missing`
  - target folder does not exist yet
  - in Freya mode, create project folders with `bootstrap_project`
  - in generic mode, create the parent folder manually in Obsidian first

### 8. Safety reminders

- In Freya mode, the mistake log is append-only through the specialized tool.
- `move_note` is never exposed unless `--allow-move` is explicitly enabled.
- Do not run multiple write-capable instances against the same vault at the same time.

## Safety

This server is intentionally conservative.

Key protections:

- vault path is resolved once at startup and cannot be overridden per tool call
- hidden files and symlinked paths are rejected
- write access is controlled by a whitelist, not a broad prefix
- append-only files can be protected by workflow defaults or env overrides
- API token redaction is enforced in logs, envelopes, and exception handling
- `read-only` mode disables all write operations without changing client config shape

Think of it like putting a guardrail around a shared notebook: the agent can still write, but only in the lanes you explicitly allow.

## Development

```bash
git clone https://github.com/ibanunmangun/obsidian-mcp.git
cd obsidian-mcp
<python> -m pip install -e .[dev]
<python> -m pytest tests/ -x -q
<python> -m ruff check src tests
```

## License

Apache-2.0.
