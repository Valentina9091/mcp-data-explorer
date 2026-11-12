# MCP Data Explorer

**AI-Powered Data Exploration | Python • MCP • DuckDB • SQL**

A Python-based Model Context Protocol (MCP) server that enables AI assistants like Claude to explore, query, validate, and visualize local datasets using natural language.

Instead of manually writing SQL or Python scripts, users can ask questions about their data, and the AI assistant uses the MCP server to perform the analysis.

## Overview

MCP Data Explorer bridges AI assistants and structured datasets by exposing secure, read-only data exploration tools.

The application supports CSV, JSON, and Parquet files and uses DuckDB for efficient SQL-based analytics.

**Example questions:**

- "What datasets are available?"
- "Find duplicate orders and missing customer information."
- "Calculate total revenue by product."
- "Identify unusual prices and negative quantities."
- "Generate a bar chart showing monthly sales."

## Key Features

| Feature | Description |
|---|---|
| Dataset Discovery | Automatically identifies datasets and their schemas |
| Natural Language Exploration | Allows AI assistants to translate questions into tool calls |
| SQL Analytics | Executes read-only SQL queries using DuckDB |
| Data Profiling | Examines column statistics, null values, and distributions |
| Data Quality Validation | Detects duplicates, missing values, outliers, and invalid records |
| Data Visualization | Generates bar, line, scatter, and histogram charts |
| Secure Query Execution | Restricts unsafe SQL and external data access |
| MCP Integration | Works with compatible MCP clients, including Claude |

## How It Works

```text
           User
             |
             | Natural language question
             v
      Claude / AI Assistant
             |
             | MCP tool requests
             v
       MCP Server (Python)
             |
             | Validated SQL queries
             v
        DuckDB Engine
             |
             | Reads and analyzes
             v
      CSV / JSON / Parquet
             |
             | Query results
             v
      AI Assistant Response
```

**Example workflow:**

1. User asks Claude to identify data-quality problems.
2. Claude invokes the appropriate MCP tools.
3. The server validates the request.
4. DuckDB analyzes the dataset.
5. Results are returned to Claude.
6. Claude summarizes the findings in plain English.

## Technology Stack

- **Python:** Backend implementation
- **MCP SDK:** AI-to-tool communication
- **DuckDB:** SQL query and analytics engine
- **Pandas / Matplotlib:** Data visualization and analysis capabilities
- **SQL:** Data exploration and aggregation
- **Pytest:** Automated testing
- **Claude:** Example MCP-compatible AI client

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/Valentina9091/mcp-data-explorer.git
cd mcp-data-explorer
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Generate Sample Data

```bash
python make_sample_data.py
```

This creates sample e-commerce datasets containing intentionally introduced data-quality issues for testing.

### 4. Run Tests

```bash
python test_client.py
pytest -q
```

### 5. Start the MCP Server

```bash
python server.py --data-dir data
```

The server is now ready for an MCP client using standard input/output communication.

## Connect to Claude

### Claude Code

```bash
claude mcp add data-explorer -- python /ABS/PATH/server.py --data-dir /ABS/PATH/data
```

Replace the example paths with the absolute paths on your machine.

### Claude Desktop

Add the following to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "data-explorer": {
      "command": "python",
      "args": [
        "/ABS/PATH/server.py",
        "--data-dir",
        "/ABS/PATH/data"
      ]
    }
  }
}
```

Restart Claude Desktop after saving the configuration.

## Available MCP Tools

| Tool | Purpose |
|---|---|
| `list_datasets` | Discover available datasets |
| `describe_table` | Inspect schemas and sample records |
| `query` | Execute read-only SQL |
| `profile_column` | Analyze individual column statistics |
| `data_quality_report` | Detect common data-quality problems |
| `chart` | Generate visualizations from query results |

The server also exposes MCP resources and reusable prompts for guided dataset exploration.

## Example SQL Query

Calculate revenue by product:

```sql
SELECT
    product,
    SUM(price * quantity) AS revenue
FROM orders
GROUP BY product
ORDER BY revenue DESC;
```

Claude can generate this query, execute it through the MCP server, and explain the results.

## Data Quality Checks

The project supports checks for:

- Duplicate records and duplicate keys
- Missing or null values
- Negative numeric values
- Unexpected statistical outliers
- Invalid or future dates

The sample datasets include deliberately introduced problems to demonstrate these capabilities.

## Security and Reliability

The server is designed around controlled, read-only data access.

- Validates SQL statements before execution
- Prevents modification of source datasets through SQL tools
- Disables arbitrary external access from DuckDB queries
- Validates table and column references
- Limits query output to prevent oversized responses
- Provides useful error messages for invalid queries
- Supports user confirmation for queries that may scan large datasets

For remote access, authentication and appropriate network security should be configured.

## Additional Capabilities

**Data Visualization**

The `chart` tool generates PNG visualizations using Matplotlib.

Supported chart types include bar, line, scatter, and histogram.

**Progress Notifications**

Long-running data-quality checks can report progress to compatible MCP clients.

**Large Query Confirmation**

The server supports confirmation requests when estimated query scans exceed a configurable row threshold.

**HTTP Support**

The MCP server can also run using Streamable HTTP:

```bash
python server.py --data-dir data --http
```

Default local endpoint:

`http://127.0.0.1:8000/mcp`

## Project Structure

```text
mcp-data-explorer/
├── data/                 # Sample datasets
├── server.py             # MCP server implementation
├── ask.py                # Command-line MCP client
├── make_sample_data.py   # Sample dataset generator
├── test_client.py        # End-to-end MCP tests
├── test_server.py        # Server unit/integration tests
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

## Future Enhancements

Potential improvements include:

- PostgreSQL, Snowflake, and BigQuery integrations
- Additional automated data-quality rules
- More advanced visualizations
- Support for large-scale datasets
- AI-assisted recommendations for resolving data-quality issues

## Project Purpose

This project demonstrates how to integrate AI assistants with real data systems using MCP.

It combines backend engineering, SQL analytics, data validation, secure tool execution, and AI integration to make structured data easier to explore.

