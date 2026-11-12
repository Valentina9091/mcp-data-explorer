"""End-to-end smoke test: launches server.py as a subprocess over stdio (exactly how
Claude Desktop runs it) and exercises every tool, resource and prompt."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

HERE = Path(__file__).parent


def show(title: str, result) -> None:
    print(f"\n=== {title} ===")
    if getattr(result, "structured_content", None) is not None:
        print(json.dumps(result.structured_content, indent=2)[:1500])
    else:
        for block in result.content:
            print(getattr(block, "text", block)[:1500])


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "server.py"), "--data-dir", str(HERE / "data")],
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools.tools])

        show("list_datasets", await client.call_tool("list_datasets", {}))
        show("describe_table(customers)", await client.call_tool("describe_table", {"table": "customers", "sample_rows": 2}))
        show("query: revenue by region", await client.call_tool("query", {"sql": """
            SELECT c.region, ROUND(SUM(o.quantity * o.unit_price * (1 - o.discount_pct/100)), 2) AS revenue,
                   COUNT(*) AS orders
            FROM orders o JOIN customers c USING (customer_id)
            GROUP BY 1 ORDER BY revenue DESC"""}))
        show("profile_column(orders.unit_price)", await client.call_tool("profile_column", {"table": "orders", "column": "unit_price", "top_n": 3}))
        show("data_quality_report(orders)", await client.call_tool("data_quality_report", {"table": "orders"}))
        show("data_quality_report(orders, group_by=product)",
             await client.call_tool("data_quality_report", {"table": "orders", "group_by": "product"}))
        show("data_quality_report(customers)", await client.call_tool("data_quality_report", {"table": "customers"}))

        # Guardrails: these must all be rejected
        for bad in ["DROP TABLE orders", "SELEC broken sql",
                    "SELECT * FROM read_csv('/etc/passwd')",
                    "SELECT 1; DELETE FROM orders",
                    "SET enable_external_access = true"]:
            r = await client.call_tool("query", {"sql": bad})
            msg = r.content[0].text if r.content else ""
            print(f"\nguardrail [{bad[:40]}] -> isError={r.is_error}: {msg[:110]}")
            assert r.is_error, f"expected rejection for: {bad}"

        res = await client.list_resources()
        print("\nresources:", [str(r.uri) for r in res.resources])
        templates = await client.list_resource_templates()
        print("templates:", [t.uri_template for t in templates.resource_templates])
        print((await client.read_resource("schema://all")).contents[0].text)
        print((await client.read_resource("table://orders/sample")).contents[0].text[:200])

        prompt = await client.get_prompt("explore_dataset", {"table": "orders", "question": "Which products drive revenue?"})
        print("\nprompt:", prompt.messages[0].content.text)
        print("\nALL CHECKS PASSED")


asyncio.run(main())
