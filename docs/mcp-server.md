# Forven MCP Server

Expose the AI Drop Zone to Claude Desktop (or any MCP client) as a set of
tools, so strategy generation becomes a conversation instead of a
copy-paste loop.

## What it is

An MCP server that wraps the running Forven HTTP API. It speaks the
Model Context Protocol over stdio — Claude Desktop spawns the process,
reads the tool list, and calls tools on your behalf as you chat.

## Prerequisites

- Forven backend running (`forven serve` or `python -m uvicorn forven.api:app --port 8003`)
- Python environment where `forven` is importable (the same venv you run the backend from is fine)
- Claude Desktop installed, or any other MCP client

## Run locally

```bash
python -m forven.mcp_server
```

The process reads MCP frames from stdin and writes to stdout, so running
it in a terminal mostly looks like it's hanging. That's expected — it's
waiting for a client.

### Configuration

All via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `FORVEN_API_URL` | `http://127.0.0.1:8003` | Backend base URL |
| `FORVEN_API_KEY` | *(empty)* | Sent as `x-api-key` when set |
| `FORVEN_OPERATOR_KEY` | *(empty)* | Sent as `x-operator-key` when set |
| `FORVEN_MCP_TIMEOUT` | `60` | HTTP timeout in seconds |

If `FORVEN_AUTH_REQUIRED=true` on the backend, you MUST set
`FORVEN_API_KEY` and `FORVEN_OPERATOR_KEY` or every tool call will 401.

## Wire to Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "forven": {
      "command": "python",
      "args": ["-m", "forven.mcp_server"],
      "env": {
        "FORVEN_API_URL": "http://127.0.0.1:8003",
        "FORVEN_API_KEY": "your-api-key",
        "FORVEN_OPERATOR_KEY": "your-operator-key"
      }
    }
  }
}
```

If your `python` isn't on PATH inside Claude Desktop's spawn env, use the
absolute path to the interpreter (e.g. `C:\Users\you\venvs\forven\Scripts\python.exe`).

Restart Claude Desktop. You should see a hammer/tool icon in the chat UI
— click it to confirm the `forven_*` tools are loaded.

## Tool reference

### Read-only

| Tool | Purpose |
|---|---|
| `forven_get_context` | Full AI Drop Zone context (template, datasets, endpoints, workflow). Call first. |
| `forven_list_sessions` | Recent sessions with strategy counts. |
| `forven_get_session` | Strategies + runs tagged to a session. |
| `forven_list_strategies` | Registered strategies. |
| `forven_get_recent_runs` | Last N backtest runs. |
| `forven_get_result` | Metrics + trades + config for one result. |
| `forven_get_quant_skills` | Curated insights by regime. Check before designing. |

### Write

| Tool | Purpose |
|---|---|
| `forven_create_session` | Open a session (returns id like `ADZ-0007`). |
| `forven_close_session` | Mark a session closed. Idempotent. |
| `forven_register_strategy_file` | Register one .py file. Tags to session if provided. |
| `forven_run_backtest` | Run a backtest. Tags to session if provided. |

## Typical workflow inside Claude Desktop

```
> Open a session for "RSI mean reversion iteration 3"
Claude calls forven_create_session → returns ADZ-0007

> Design and register a novel RSI strategy for BTC-1h
Claude calls forven_get_context, forven_get_quant_skills(regime="range_bound"),
writes a .py file into the workspace, calls forven_register_strategy_file
with session_id="ADZ-0007" → returns strategy_id

> Backtest it
Claude calls forven_run_backtest(strategy_id, dataset_id="BTC/USDT-1h",
session_id="ADZ-0007") → returns result

> Show me what I've tried this session
Claude calls forven_get_session("ADZ-0007") → summary of every strategy
and run under this session
```

## Troubleshooting

**"Tool call timed out"** — increase `FORVEN_MCP_TIMEOUT`. Full backtests
can take minutes on cold caches.

**"401 Invalid or missing operator key"** — the backend has auth enabled
but the MCP env is missing `FORVEN_OPERATOR_KEY`. Set it in the
Claude Desktop config `env` block.

**"Connection refused"** — backend isn't running or is on a different
port than `FORVEN_API_URL`.

**Tools don't appear in Claude Desktop** — check the Desktop logs
(`%APPDATA%\Claude\logs\mcp-server-forven.log` on Windows). Common
causes: `python` not on PATH, `forven` not importable in the spawned
env, or the config JSON has a syntax error.
