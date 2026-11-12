"""
data-explorer: an MCP server that lets an AI assistant explore local CSV/Parquet data
with read-only SQL (DuckDB), column profiling, and data-quality checks.

Run:  python server.py --data-dir ./data          (stdio transport, for Claude Desktop etc.)
      python server.py --data-dir ./data --http   (Streamable HTTP on :8000/mcp)

MCP concepts demonstrated:
  * Tools      - functions the model can call (list_datasets, describe_table, query, ...)
  * Resources  - read-only context the client can attach (schema://all, table://{name}/sample)
  * Prompts    - reusable, parameterised workflows (explore_dataset)
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

SUPPORTED = {".csv": "read_csv_auto", ".parquet": "read_parquet", ".json": "read_json_auto"}
MAX_ROWS = 1000
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


# --------------------------------------------------------------------------- data layer
class Catalog:
    """Loads files from a directory into an in-memory DuckDB, then locks it down."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.con = duckdb.connect(":memory:")
        self.sources: dict[str, str] = {}
        for path in sorted(self.data_dir.iterdir()):
            reader = SUPPORTED.get(path.suffix.lower())
            if not reader:
                continue
            name = re.sub(r"\W+", "_", path.stem).strip("_").lower() or "table"
            self.con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM {reader}(?)', [str(path)])
            self.sources[name] = path.name
        # Sandbox: after loading, SQL can no longer touch the filesystem or network,
        # and the setting itself can't be flipped back by a query.
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    # -- helpers
    def columns(self, table: str) -> list[tuple[str, str]]:
        self.require_table(table)
        return [(r[0], r[1]) for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()]

    def require_table(self, table: str) -> None:
        if table not in self.sources:
            raise ToolError(f"Unknown table '{table}'. Available: {', '.join(self.sources) or 'none'}")

    def require_column(self, table: str, column: str) -> str:
        types = dict(self.columns(table))
        if column not in types:
            raise ToolError(f"Unknown column '{column}' in {table}. Columns: {', '.join(types)}")
        return types[column]

    def rows(self, sql: str, params: list | None = None, limit: int | None = None) -> dict[str, Any]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        data = cur.fetchmany(limit) if limit else cur.fetchall()
        truncated = bool(limit) and cur.fetchone() is not None
        return {"columns": cols, "rows": [[_jsonable(v) for v in r] for r in data], "truncated": truncated}

    def scalar(self, sql: str, params: list | None = None) -> Any:
        return _jsonable(self.con.execute(sql, params or []).fetchone()[0])


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return round(v, 4)
    return v


def _is_numeric(dtype: str) -> bool:
    return any(t in dtype.upper() for t in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC"))


def _is_temporal(dtype: str) -> bool:
    return any(t in dtype.upper() for t in ("DATE", "TIMESTAMP"))


# --------------------------------------------------------------------------- server
mcp = MCPServer(
    name="data-explorer",
    version="0.1.0",
    instructions=(
        "Explore local tabular datasets. Start with list_datasets, then describe_table. "
        "Use query for read-only DuckDB SQL (SELECT/WITH only). Use data_quality_report "
        "before trusting a table for analysis."
    ),
)
catalog: Catalog  # set in main()


@mcp.tool(annotations=READ_ONLY)
def list_datasets() -> dict[str, Any]:
    """List every table available for analysis, with its source file, row count and column count."""
    out = []
    for name, src in catalog.sources.items():
        out.append({
            "table": name,
            "source_file": src,
            "rows": catalog.scalar(f'SELECT COUNT(*) FROM "{name}"'),
            "columns": len(catalog.columns(name)),
        })
    return {"data_dir": str(catalog.data_dir), "tables": out}


@mcp.tool(annotations=READ_ONLY)
def describe_table(table: str, sample_rows: int = 5) -> dict[str, Any]:
    """Show a table's schema (column, type, null %, distinct count) plus a few sample rows."""
    cols = catalog.columns(table)
    total = catalog.scalar(f'SELECT COUNT(*) FROM "{table}"') or 0
    schema = []
    for col, dtype in cols:
        nulls, distinct = catalog.con.execute(
            f'SELECT COUNT(*) - COUNT("{col}"), COUNT(DISTINCT "{col}") FROM "{table}"'
        ).fetchone()
        schema.append({
            "column": col,
            "type": dtype,
            "null_pct": round(100 * nulls / total, 2) if total else 0.0,
            "distinct": distinct,
        })
    sample = catalog.rows(f'SELECT * FROM "{table}" LIMIT ?', [max(0, min(sample_rows, 50))])
    return {"table": table, "rows": total, "schema": schema, "sample": sample}


@mcp.tool(annotations=READ_ONLY)
def query(sql: str, max_rows: int = 200) -> dict[str, Any]:
    """Run a single read-only DuckDB SQL statement (SELECT / WITH / DESCRIBE / SUMMARIZE).

    Tables are named after their source files (see list_datasets). Results are capped at
    max_rows (<= 1000); 'truncated' tells you if more rows exist - aggregate instead of paging.
    """
    try:
        statements = catalog.con.extract_statements(sql)
    except duckdb.Error as e:
        raise ToolError(f"SQL parse error: {e}") from e
    if len(statements) != 1:
        raise ToolError("Send exactly one SQL statement.")
    allowed = {duckdb.StatementType.SELECT}
    first_word = sql.strip().split(None, 1)[0].upper()
    if statements[0].type not in allowed and first_word not in {"DESCRIBE", "SUMMARIZE", "SHOW"}:
        raise ToolError(f"Only read-only queries are allowed (got {statements[0].type.name}).")
    try:
        return catalog.rows(sql, limit=max(1, min(max_rows, MAX_ROWS)))
    except duckdb.Error as e:
        # Hand the real error back so the model can fix its SQL and retry.
        raise ToolError(f"{type(e).__name__}: {e}") from e


@mcp.tool(annotations=READ_ONLY)
def profile_column(table: str, column: str, top_n: int = 10) -> dict[str, Any]:
    """Statistical profile of one column: nulls, distinct, top values, and (for numeric /
    date columns) min, max, mean, stddev and quartiles."""
    dtype = catalog.require_column(table, column)
    t, c = f'"{table}"', f'"{column}"'
    total, nulls, distinct = catalog.con.execute(
        f"SELECT COUNT(*), COUNT(*) - COUNT({c}), COUNT(DISTINCT {c}) FROM {t}"
    ).fetchone()
    prof: dict[str, Any] = {
        "table": table, "column": column, "type": dtype,
        "rows": total, "nulls": nulls, "distinct": distinct,
        "top_values": catalog.rows(
            f"SELECT {c} AS value, COUNT(*) AS n FROM {t} GROUP BY 1 ORDER BY n DESC, 1 LIMIT ?",
            [max(1, min(top_n, 50))],
        )["rows"],
    }
    if _is_numeric(dtype):
        r = catalog.con.execute(
            f"SELECT MIN({c}), MAX({c}), AVG({c}), STDDEV_SAMP({c}), "
            f"QUANTILE_CONT({c}, [0.25, 0.5, 0.75]) FROM {t}"
        ).fetchone()
        prof.update(min=_jsonable(r[0]), max=_jsonable(r[1]), mean=_jsonable(r[2]),
                    stddev=_jsonable(r[3]), quartiles=[_jsonable(q) for q in (r[4] or [])])
    elif _is_temporal(dtype):
        r = catalog.con.execute(f"SELECT MIN({c}), MAX({c}) FROM {t}").fetchone()
        prof.update(min=_jsonable(r[0]), max=_jsonable(r[1]))
    return prof


@mcp.tool(annotations=READ_ONLY)
def data_quality_report(table: str, key_column: str | None = None,
                        group_by: str | None = None) -> dict[str, Any]:
    """Run data-quality checks on a table and return a list of issues with severity.

    Checks: missing values, fully duplicated rows, duplicate keys (key_column, or the first
    column named 'id' / '*_id'), IQR outliers and negative values in numeric columns, and
    dates in the future. Pass group_by (e.g. a product or category column) to judge
    outliers within each group instead of across the whole column.
    """
    cols = catalog.columns(table)
    if group_by:
        catalog.require_column(table, group_by)
    t = f'"{table}"'
    total = catalog.scalar(f"SELECT COUNT(*) FROM {t}") or 0
    issues: list[dict[str, Any]] = []

    def add(severity: str, check: str, column: str | None, detail: str, count: int) -> None:
        issues.append({"severity": severity, "check": check, "column": column,
                       "affected_rows": count, "detail": detail})

    dupes = catalog.scalar(f"SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {t})) FROM {t}")
    if dupes:
        add("high", "duplicate_rows", None, f"{dupes} rows are exact duplicates of another row", dupes)

    keys = [key_column] if key_column else [
        col for col, _ in cols
        if col.lower().endswith("_id") or col.lower() == "id"
    ][:1]
    for key in keys:
        catalog.require_column(table, key)
        dup_keys = catalog.scalar(
            f'SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) n FROM {t} '
            f'WHERE "{key}" IS NOT NULL GROUP BY "{key}" HAVING n > 1)'
        )
        if dup_keys:
            add("high", "duplicate_key", key, f"'{key}' is not unique: {dup_keys} extra rows share a key", int(dup_keys))

    for col, dtype in cols:
        c = f'"{col}"'
        nulls = catalog.scalar(f"SELECT COUNT(*) - COUNT({c}) FROM {t}")
        if nulls:
            pct = 100 * nulls / total
            add("high" if pct > 20 else "medium" if pct > 5 else "low", "missing_values", col,
                f"{pct:.1f}% of values are null", nulls)

        is_id = col.lower().endswith("_id") or col.lower() == "id"
        if _is_numeric(dtype) and not is_id and col != group_by:
            # 3xIQR fences, computed per group when group_by is set (e.g. price per product),
            # because one global fence misfires on multi-modal columns.
            g = f'"{group_by}"' if group_by else "1"
            n = catalog.scalar(f"""
                WITH f AS (SELECT {g} AS grp, QUANTILE_CONT({c}, 0.25) q1, QUANTILE_CONT({c}, 0.75) q3
                           FROM {t} GROUP BY 1)
                SELECT COUNT(*) FROM {t} JOIN f ON ({g}) IS NOT DISTINCT FROM f.grp
                WHERE f.q3 > f.q1 AND ({c} < f.q1 - 3*(f.q3-f.q1) OR {c} > f.q3 + 3*(f.q3-f.q1))""")
            if n:
                scope = f"within each {group_by}" if group_by else "across the whole column"
                hint = ("" if group_by or n < 0.05 * total else
                        " - that's a lot; the column may be multi-modal, retry with group_by")
                add("medium", "outliers", col, f"{n} values outside the 3xIQR fence {scope}{hint}", n)
            neg = catalog.scalar(f"SELECT COUNT(*) FROM {t} WHERE {c} < 0")
            if neg and not any(k in col.lower() for k in ("delta", "change", "diff", "balance", "lat", "lon")):
                add("medium", "negative_values", col, f"{neg} negative values", neg)

        if _is_temporal(dtype):
            fut = catalog.scalar(f"SELECT COUNT(*) FROM {t} WHERE CAST({c} AS DATE) > current_date")
            if fut:
                add("medium", "future_dates", col, f"{fut} dates are after today", fut)

    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (order[i["severity"]], -i["affected_rows"]))
    return {"table": table, "rows": total, "issue_count": len(issues),
            "passed": not issues, "issues": issues}


# --------------------------------------------------------------------------- resources
@mcp.resource("schema://all", mime_type="text/markdown", description="Schema of every loaded table")
def all_schemas() -> str:
    lines = [f"# Datasets in {catalog.data_dir}\n"]
    for name, src in catalog.sources.items():
        lines.append(f"## {name}  (from `{src}`)")
        lines += [f"- `{col}`: {dtype}" for col, dtype in catalog.columns(name)]
        lines.append("")
    return "\n".join(lines)


@mcp.resource("table://{name}/sample", mime_type="text/csv", description="First 20 rows of a table as CSV")
def table_sample(name: str) -> str:
    catalog.require_table(name)
    res = catalog.rows(f'SELECT * FROM "{name}" LIMIT 20')
    out = [",".join(res["columns"])]
    out += [",".join("" if v is None else str(v) for v in row) for row in res["rows"]]
    return "\n".join(out)


# --------------------------------------------------------------------------- prompts
@mcp.prompt(description="Guided exploratory analysis of one table")
def explore_dataset(table: str, question: str = "What are the most important patterns?") -> str:
    return (
        f"You are a careful data analyst. Investigate the table `{table}`.\n"
        f"1. Call describe_table to learn the schema.\n"
        f"2. Call data_quality_report and note any issues that could bias results.\n"
        f"3. Use query (aggregations, not raw dumps) to answer: {question}\n"
        f"4. Report findings with the SQL you used, and flag every caveat from step 2."
    )


# --------------------------------------------------------------------------- entrypoint
def main() -> None:
    global catalog
    p = argparse.ArgumentParser(description="data-explorer MCP server")
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "./data"))
    p.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    args = p.parse_args()
    catalog = Catalog(Path(args.data_dir))
    mcp.run("streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    main()
