# data-explorer — an MCP server for exploring local data

Point any MCP client at a folder of CSV / Parquet / JSON files and it can
explore them: list tables, read schemas, run **read-only** SQL via DuckDB, profile
columns, run data-quality checks, and draw charts.

## What MCP is

**Model Context Protocol** is an open standard (JSON-RPC 2.0 underneath) for connecting AI
apps to tools and data. You write one *server*, and any MCP *client* — desktop chat apps,
coding assistants, IDEs, your own agents — can use it.

```
 ┌──────────── Host (chat app / IDE / agent) ─────────────────┐
 │  LLM  ◀──▶  MCP client  ── stdio or HTTP (JSON-RPC) ──▶  MCP server ──▶ DuckDB ──▶ data/*.csv
 └─────────────────────────────────────────────────────────────┘
```

A server exposes three primitives:

| Primitive | Who decides to use it | In this project |
|---|---|---|
| **Tools** — functions with a JSON schema | the **model** | `list_datasets`, `describe_table`, `query`, `chart`, `profile_column`, `data_quality_report` |
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

Beyond the three primitives, tools can use the request **`Context`**:

| Feature | In this project |
|---|---|
| **Image content** — a tool returns a PNG as `ImageContent` | `chart(sql, kind, x, y, title)` → bar / line / scatter / histogram via matplotlib (`return Image(data=png, format="png")`) |
| **Progress** — `ctx.report_progress(i, total, msg)` | `data_quality_report` reports once per column checked |
| **Elicitation** — the server asks the user a question mid-call | `query` / `chart` ask for confirmation when the referenced tables hold more than `--confirm-rows` rows (default 1,000,000; env `CONFIRM_ROWS`) |

Elicitation is written as a **resolver**, so the SDK picks the transport for the negotiated
protocol (an `InputRequiredResult` the client answers and retries on 2026-07-28, a mid-call
`elicitation/create` request on older protocols):

```python
def _scan_check(sql: str, ctx: Context) -> ScanConfirmation | Elicit[ScanConfirmation]:
    if catalog.estimated_scan_rows(sql) <= CONFIRM_ROWS or not ctx.client_capabilities.elicitation:
        return ScanConfirmation(proceed=True)          # no question needed
    return Elicit("This query scans ~N rows. Run it?", ScanConfirmation)

@mcp.tool()
def query(sql: str, confirm: Annotated[ElicitationResult[ScanConfirmation], Resolve(_scan_check)]): ...
```

`confirm` never appears in the tool's input schema; the model only sees `sql` and `max_rows`.
Clients without elicitation support skip the prompt, because the server is read-only anyway.

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
pytest -q                           # in-process tests (Client(mcp), no subprocess): tools, chart, progress, elicitation
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

## Extend it

1. **Point it at real data** — drop your own CSV/Parquet files into `data/`.
2. **Add a Postgres/Snowflake/BigQuery backend** behind the same tools (use a read-only role).
3. ~~**Add a `chart` tool** that returns a PNG as MCP `ImageContent`.~~ Done: `chart`.
4. ~~**Use `Context`** for progress notifications on long profiles (`ctx.report_progress`).~~ Done: `data_quality_report`.
5. ~~**Elicitation** — ask the user to confirm before running a query that scans > N rows.~~ Done: `--confirm-rows`.
6. ~~**Write pytest tests** using `Client(mcp)` in-process (no subprocess needed).~~ Done: `test_server.py`.
7. **Sampling** — let `data_quality_report` ask the client's LLM to explain each issue in plain English (`Sample` resolver).
