# data-explorer — an MCP server for exploring local data

Point Claude (or any MCP client) at a folder of CSV / Parquet / JSON files and it can
explore them: list tables, read schemas, run **read-only** SQL via DuckDB, profile
columns, and run data-quality checks.

## What MCP is

**Model Context Protocol** is an open standard (JSON-RPC 2.0 underneath) for connecting AI
apps to tools and data. You write one *server*, and any MCP *client* — Claude Desktop,
Claude Code, IDEs, your own agents — can use it.

```
 ┌──────────── Host (Claude Desktop / Claude Code) ────────────┐
 │  LLM  ◀──▶  MCP client  ── stdio or HTTP (JSON-RPC) ──▶  MCP server ──▶ DuckDB ──▶ data/*.csv
 └─────────────────────────────────────────────────────────────┘
```

A server exposes three primitives:

| Primitive | Who decides to use it | In this project |
|---|---|---|
| **Tools** — functions with a JSON schema | the **model** | `list_datasets`, `describe_table`, `query`, `profile_column`, `data_quality_report` |
| **Resources** — read-only data at a URI | the **app / user** attaches them | `schema://all`, `table://{name}/sample` (a URI *template*) |
| **Prompts** — reusable templated workflows | the **user** picks them (e.g. slash command) | `explore_dataset(table, question)` |

Lifecycle: client launches/connects → `initialize` (capability negotiation) →
`tools/list` → model chooses a tool → `tools/call` → result goes back into the model's context.

The Python SDK turns type hints + docstrings into the JSON schema, so a tool is just a function:

```python
@mcp.tool(annotations=READ_ONLY)
def profile_column(table: str, column: str, top_n: int = 10) -> dict: ...
```

> Note: this targets **`mcp` 2.x**, where v1's `FastMCP` was renamed `MCPServer`
> (`from mcp.server.mcpserver import MCPServer`). Most tutorials online still show v1.

## Design decisions worth noticing

- **Security is the server's job.** The model writes the SQL, so the server can't trust it:
  1. only one statement, and it must parse as `SELECT` (or `DESCRIBE`/`SUMMARIZE`/`SHOW`);
  2. files are loaded into an in-memory DB at startup, then `enable_external_access=false` +
     `lock_configuration=true` — so even a "SELECT" can't do `read_csv('/etc/passwd')`, and
     the setting can't be flipped back;
  3. table/column names are checked against the catalog before they're interpolated.
- **Errors are for the model.** Expected failures raise `ToolError` with the real DuckDB
  message, so the model can fix its SQL and retry instead of seeing a generic failure.
- **Bounded output.** Results are capped (≤1000 rows) with a `truncated` flag — context
  windows are the scarce resource, so tools should return aggregates, not dumps.
- **Tool annotations** (`readOnlyHint`, `idempotentHint`) let clients skip confirmation prompts.
- **Descriptions are prompts.** Docstrings are what the model reads to decide when to call a
  tool — e.g. `data_quality_report` tells it about `group_by`, and its output suggests retrying
  with `group_by` when a global outlier fence flags too many rows.

## Run it

```bash
pip install -r requirements.txt
python make_sample_data.py          # e-commerce sample with planted data-quality bugs
python test_client.py               # end-to-end test over stdio: every tool, resource, prompt + guardrails
```

Interactive debugging with the official inspector UI:

```bash
npx @modelcontextprotocol/inspector python server.py --data-dir data
```

### Connect to Claude Code

```bash
claude mcp add data-explorer -- python /ABS/PATH/server.py --data-dir /ABS/PATH/data
```

### Connect to Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "data-explorer": {
      "command": "python",
      "args": ["/ABS/PATH/server.py", "--data-dir", "/ABS/PATH/data"]
    }
  }
}
```

Restart, then try: *"Use data-explorer to check the orders table for quality problems,
then tell me revenue by product excluding the bad rows."*

### Remote (Streamable HTTP)

```bash
python server.py --data-dir data --http      # serves http://127.0.0.1:8000/mcp
```

For anything beyond localhost, put auth in front (the SDK supports OAuth via `auth=`/`token_verifier=`).

## What the sample data contains (and what the server finds)

| Planted issue | Found by |
|---|---|
| duplicate `order_id` | `duplicate_key` |
| 6 fat-finger prices (×40) | `outliers` with `group_by="product"` (globally, laptops drown the signal → 833 false hits + a hint to group) |
| 4 negative quantities (returns) | `negative_values` |
| 3 orders dated 2027 | `future_dates` |
| duplicate customer row, ~8–11% missing emails | `duplicate_rows`, `duplicate_key`, `missing_values` |

## Extend it (good next exercises)

1. **Point it at real data** — drop your own CSV/Parquet files into `data/`.
2. **Add a Postgres/Snowflake/BigQuery backend** behind the same tools (use a read-only role).
3. **Add a `chart` tool** that returns a PNG as MCP `ImageContent`.
4. **Use `Context`** for progress notifications on long profiles (`ctx.report_progress`).
5. **Elicitation** — ask the user to confirm before running a query that scans > N rows.
6. **Write pytest tests** using `Client(mcp)` in-process (no subprocess needed).
