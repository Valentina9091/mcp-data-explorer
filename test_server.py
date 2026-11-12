"""In-process tests: Client(mcp) talks to the server object directly - no subprocess.

Run:  pytest -q
"""

import base64
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import ElicitResult, ImageContent

import server

HERE = Path(__file__).parent
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(server, "catalog", server.Catalog(HERE / "data"), raising=False)
    monkeypatch.setattr(server, "CONFIRM_ROWS", 1_000_000)


def answer(action: str, proceed: bool = True):
    """Build an elicitation callback that records prompts and replies with `action`."""
    seen: list[str] = []

    async def cb(context, params):
        seen.append(params.message)
        return ElicitResult(action=action, content={"proceed": proceed} if action == "accept" else None)

    cb.seen = seen
    return cb


# ----------------------------------------------------------------- core tools
@pytest.mark.anyio
async def test_list_and_describe():
    async with Client(server.mcp) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"list_datasets", "describe_table", "query", "chart",
                "profile_column", "data_quality_report"} <= names
        tables = (await c.call_tool("list_datasets", {})).structured_content["tables"]
        assert {t["table"]: t["rows"] for t in tables} == {"customers": 501, "orders": 5000}
        desc = (await c.call_tool("describe_table", {"table": "orders", "sample_rows": 2})).structured_content
        assert len(desc["sample"]["rows"]) == 2


@pytest.mark.anyio
async def test_query_join_using():
    async with Client(server.mcp) as c:
        r = await c.call_tool("query", {"sql": "SELECT COUNT(*) AS n FROM orders JOIN customers USING (customer_id)"})
        assert not r.is_error
        assert r.structured_content["rows"][0][0] > 0


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [
    "DROP TABLE orders", "SELEC broken sql", "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT 1; DELETE FROM orders", "SET enable_external_access = true",
])
async def test_guardrails(bad):
    async with Client(server.mcp) as c:
        assert (await c.call_tool("query", {"sql": bad})).is_error


@pytest.mark.anyio
async def test_quality_report_finds_planted_issues():
    async with Client(server.mcp) as c:
        rep = (await c.call_tool("data_quality_report", {"table": "orders", "group_by": "product"})).structured_content
        checks = {i["check"] for i in rep["issues"]}
        assert {"duplicate_key", "outliers", "negative_values", "future_dates"} <= checks


# ----------------------------------------------------------------- progress
@pytest.mark.anyio
async def test_quality_report_reports_progress():
    updates = []

    async def on_progress(progress, total, message):
        updates.append((progress, total, message))

    async with Client(server.mcp) as c:
        r = await c.call_tool("data_quality_report", {"table": "orders"}, progress_callback=on_progress)
    assert not r.is_error
    assert updates, "expected progress notifications"
    assert updates[-1][0] == updates[-1][1]  # finished at 100%


# ----------------------------------------------------------------- chart
@pytest.mark.anyio
@pytest.mark.parametrize("args", [
    {"sql": "SELECT product, SUM(quantity) AS units FROM orders GROUP BY 1 ORDER BY 2 DESC"},
    {"sql": "SELECT date_trunc('month', order_date) AS m, COUNT(*) AS n FROM orders GROUP BY 1 ORDER BY 1",
     "kind": "line"},
    {"sql": "SELECT quantity, unit_price FROM orders", "kind": "scatter"},
    {"sql": "SELECT unit_price FROM orders WHERE unit_price < 2000", "kind": "histogram"},
])
async def test_chart_returns_png(args):
    async with Client(server.mcp) as c:
        r = await c.call_tool("chart", args)
    assert not r.is_error, r.content
    img = r.content[0]
    assert isinstance(img, ImageContent) and img.mime_type == "image/png"
    assert base64.b64decode(img.data).startswith(PNG_MAGIC)


@pytest.mark.anyio
@pytest.mark.parametrize("args", [
    {"sql": "SELECT 1 AS a", "kind": "pie"},
    {"sql": "SELECT product FROM orders", "kind": "histogram"},
    {"sql": "SELECT product, region FROM orders", "y": ["nope"]},
    {"sql": "DROP TABLE orders"},
])
async def test_chart_rejects_bad_input(args):
    async with Client(server.mcp) as c:
        assert (await c.call_tool("chart", args)).is_error


# ----------------------------------------------------------------- elicitation
@pytest.mark.anyio
async def test_small_query_does_not_elicit(monkeypatch):
    cb = answer("decline")
    async with Client(server.mcp, elicitation_callback=cb) as c:
        r = await c.call_tool("query", {"sql": "SELECT COUNT(*) FROM customers"})
    assert not r.is_error and cb.seen == []


@pytest.mark.anyio
@pytest.mark.parametrize("action,proceed,ok", [
    ("accept", True, True), ("accept", False, False), ("decline", True, False), ("cancel", True, False),
])
async def test_large_scan_elicits(monkeypatch, action, proceed, ok):
    monkeypatch.setattr(server, "CONFIRM_ROWS", 1000)
    cb = answer(action, proceed)
    async with Client(server.mcp, elicitation_callback=cb) as c:
        r = await c.call_tool("query", {"sql": "SELECT COUNT(*) FROM orders"})
    assert len(cb.seen) == 1 and "5,000" in cb.seen[0]
    assert r.is_error is (not ok)


@pytest.mark.anyio
async def test_large_scan_without_elicitation_support_runs(monkeypatch):
    monkeypatch.setattr(server, "CONFIRM_ROWS", 1000)
    async with Client(server.mcp) as c:  # no elicitation_callback -> capability not advertised
        r = await c.call_tool("query", {"sql": "SELECT COUNT(*) FROM orders"})
    assert not r.is_error
