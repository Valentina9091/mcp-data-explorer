"""Tiny command-line MCP client for a running data-explorer server (HTTP mode).

Terminal 1:  python server.py --data-dir data --http
Terminal 2:  python ask.py "SELECT product, COUNT(*) AS n FROM orders GROUP BY 1 ORDER BY 2 DESC"
             python ask.py --tables
             python ask.py --chart chart.png "SELECT product, SUM(quantity) AS units FROM orders GROUP BY 1"
             python ask.py --tool data_quality_report '{"table": "orders", "group_by": "product"}'
"""

import argparse
import asyncio
import base64
import json
import sys

from mcp import Client
from mcp.types import ElicitResult, ImageContent


async def confirm_in_terminal(context, params):
    """Elicitation callback: the server asks before big scans; answer it on the terminal."""
    reply = input(f"\n[server asks] {params.message} [y/N] ").strip().lower()
    if reply in ("y", "yes"):
        return ElicitResult(action="accept", content={"proceed": True})
    return ElicitResult(action="decline")


async def on_progress(progress, total, message):
    print(f"  progress {progress:g}/{total:g} {message or ''}", file=sys.stderr)


def print_table(res: dict) -> None:
    cols, rows = res["columns"], res["rows"]
    cells = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows{', truncated' if res.get('truncated') else ''})")


async def main() -> str | None:
    p = argparse.ArgumentParser(description="Query a running data-explorer MCP server")
    p.add_argument("sql", nargs="?", help="SQL to run (or the JSON arguments with --tool)")
    p.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    p.add_argument("--tables", action="store_true", help="list tables and exit")
    p.add_argument("--chart", metavar="OUT.png", help="render the SQL as a chart into this file")
    p.add_argument("--kind", default="bar", help="chart kind: bar | line | scatter | histogram")
    p.add_argument("--tool", help="call any tool by name; positional arg is its JSON arguments")
    args = p.parse_args()

    async with Client(args.url, elicitation_callback=confirm_in_terminal) as client:
        if args.tables:
            r = await client.call_tool("list_datasets", {})
            for t in r.structured_content["tables"]:
                print(f"{t['table']:<12} {t['rows']:>7} rows  {t['columns']} cols  ({t['source_file']})")
            return

        if args.tool:
            r = await client.call_tool(args.tool, json.loads(args.sql or "{}"), progress_callback=on_progress)
        elif not args.sql:
            p.error("give some SQL, or use --tables / --tool")
        elif args.chart:
            r = await client.call_tool("chart", {"sql": args.sql, "kind": args.kind})
        else:
            r = await client.call_tool("query", {"sql": args.sql})

        if r.is_error:
            return "error: " + (r.content[0].text if r.content else "unknown")
        if args.chart and r.content and isinstance(r.content[0], ImageContent):
            with open(args.chart, "wb") as f:
                f.write(base64.b64decode(r.content[0].data))
            print(f"chart saved to {args.chart}")
        elif not args.tool and r.structured_content and "columns" in r.structured_content:
            print_table(r.structured_content)
        else:
            print(json.dumps(r.structured_content, indent=2))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))  # exit outside the client context so errors print cleanly
