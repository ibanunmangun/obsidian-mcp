# obsidian-mcp-opencode

A Python MCP server that gives AI CLI agents (OpenCode, Gemini CLI, Claude Code, and other MCP-compliant clients) safe read/write access to an Obsidian vault, via the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin.

> **Status:** Pre-implementation. PRD approved, scaffolding in place, server code in progress.

## Why

The vault is your AI's persistent memory across sessions: mistake logs, project memory, reusable patterns, per-project documentation. This MCP wraps the Local REST API plugin with hard-coded safety rules so agents can read and write without accidentally clobbering append-only logs or creating phantom folders.

## Tools (10)

**Core CRUD (5)** — `read_note`, `write_note`, `append_note`, `list_notes`, `search_vault`.
**Specialized (4)** — `get_mistake_log`, `append_mistake_log`, `get_pipeline_index`, `search_projects`.
**Bootstrap (1)** — `bootstrap_project` (the only tool that may create new project directories).

## Safety Highlights

- Vault path is set once at startup via `OBSIDIAN_VAULT_PATH` and is immutable for the process lifetime — no tool argument can override it.
- Write whitelist uses **explicit pattern matching only** (no prefix matching). Slugs validated against `^[a-z0-9][a-z0-9-]{0,79}$`. Reserved segments (`home`, `tmp`, `etc`, `Users`, `root`, `var`, `bin`, `..`) rejected.
- Append-only files (`Freya - Mistake Log.md`, `Projects/*/LOGS.md`, root `LOGS.md`) refuse `write_note` regardless of `overwrite`.
- Per-path async locks plus tail read-back verification on every protected-log append.
- API token redacted from all logs, errors, exceptions, and tracebacks.
- Read-only kill switch via `--read-only` CLI flag.

## Quick Start

> Throughout this README, replace `<python>` with the absolute path to your Python interpreter (e.g. `/usr/bin/python3`, `~/.pyenv/shims/python`, `~/miniconda/bin/python`). Shell aliases like `pytest` or `python` are discouraged.

1. Install the [Obsidian Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin (v4.0.0+) in your vault. Enable **Non-encrypted (HTTP) Server** in plugin settings.
2. Generate an API key in plugin settings.
3. Install the server:
   ```bash
   git clone https://github.com/<your-username>/obsidian-mcp-opencode.git
   cd obsidian-mcp-opencode
   <python> -m pip install -e .[dev]
   ```
4. Configure `.env`:
   ```bash
   mkdir -p ~/.config/obsidian-mcp-opencode
   cp configs/.env.example ~/.config/obsidian-mcp-opencode/.env
   ```
   Edit the file and set:
   - `OBSIDIAN_VAULT_PATH` — absolute path to your vault directory.
   - `OBSIDIAN_API_KEY` — the API key you just generated.
5. Add the MCP entry to your CLI client config.

### OpenCode (`~/.config/opencode/opencode.json`)

```json
{
  "mcp": {
    "obsidian": {
      "type": "local",
      "command": ["<python>", "-m", "obsidian_mcp_opencode"],
      "enabled": true
    }
  }
}
```

### Gemini CLI

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

### Claude Code / Desktop

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

Restart your CLI after editing the config.

## Read-Only Mode

If you want zero-write deployment for safety:

```json
"command": ["<python>", "-m", "obsidian_mcp_opencode", "--read-only"]
```

## Verification

```bash
<python> -m pytest tests/ -x -q
```

## Important Warnings

- **Single writer only.** Don't run multiple write-capable instances against the same vault concurrently — append serialization is per-process.
- **Mistake log integrity.** Always use `append_mistake_log` to add entries; direct writes to `Freya - Mistake Log.md` are rejected.
- **No delete tool.** v1 does not include destructive operations. Cleanup of failed bootstraps and smoke-test artifacts is manual.

## License

Apache-2.0.
