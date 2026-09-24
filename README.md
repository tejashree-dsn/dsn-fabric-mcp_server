# DSN Fabric MCP — curated analytics server

This is the updated MCP design for Claude Desktop. It keeps the working Service Principal + ODBC Fabric connection from the original POC, but moves the proven DSN query/reconciliation methodology into the MCP server instead of asking Claude to recreate it from schema every time.

## Architecture

```text
Claude Desktop
      |
      | MCP/stdio
      v
DSN Fabric Analytics skill
      |
      v
dsn-fabric-mcp
  |-- dsn_query                approved business workflows
  |-- dsn_catalog              targeted discovery / exact names / methodology
  |-- dsn_result               local paging + XLSX export
  |-- dsn_execute_ad_hoc_sql   bounded fallback SELECT only
  `-- health_check
      |
      | Entra Service Principal
      v
Microsoft Fabric SQL endpoint
      |-- dwh_report
      `-- lh_transform (optional, MVD)
```

## Why this is different from the original POC

The original POC exposed `get_schema()` and arbitrary `execute_sql(sql)`. That proves connectivity, but it leaves important reconciliation rules to the model. This build makes `dsn_query` the primary interface and keeps SQL/business semantics server-owned and deterministic.

The approved workflows preserve the important behavior from the automated query-pull runner: distinct transaction counting, exclusive date upper bounds, the EFS/non-EFS core definition, aggregate methodology, reference-scope rules, EOMV retail logic, MVD access, exact parent-customer detail, and Excel provenance.

## Project layout

```text
server.py
config.py
fabric_client.py
models.py
business_rules.py
query_builder.py
query_service.py
catalog_service.py
result_store.py
exporter.py
sql_validator.py
queries/
  core_transactions.sql
  parent_customer_detail.sql
  dealer_service_summary.sql
  aggregate_entity.sql
  aggregate_source.sql
  reference_entity.sql
  reference_source.sql
  eomv_retail.sql
  mvd.sql
tests/
skill/dsn-fabric-analytics/
```

## Tools

### `dsn_query`

Primary tool. Supported reports:

- `core_transactions`
- `parent_customer_detail`
- `dealer_service_summary`
- `aggregate_summary`
- `reference_summary`
- `eomv_retail`
- `mvd`

Examples of request objects:

```json
{
  "report": "core_transactions",
  "year": 2026,
  "month": 6,
  "parent_customer": "Morgan Auto Group",
  "grain": "month_agency",
  "result_mode": "preview",
  "preview_rows": 100
}
```

```json
{
  "report": "aggregate_summary",
  "from_date": "2026-01-01",
  "to_date": "2026-07-01",
  "include_all": false,
  "result_mode": "export"
}
```

The tool always caches the complete result up to `FABRIC_MAX_RESULT_ROWS`; Claude receives only the requested preview.

### `dsn_catalog`

Actions:

- `list_reports`
- `methodology`
- `list_agencies`
- `list_parent_customers`
- `list_tables`
- `describe_table`
- `search_columns`

Use this when Claude needs an exact stored parent name or agency code instead of guessing.

### `dsn_result`

Use a `query_id` returned by `dsn_query`.

```json
{
  "action": "page",
  "query_id": "...",
  "dataset": "core_transactions",
  "offset": 100,
  "limit": 100
}
```

or:

```json
{
  "action": "export",
  "query_id": "..."
}
```

Exports are `.xlsx` files with a `_pull_info` sheet containing report, scope, methodology version, warnings, row counts, template names and query hashes.

### `dsn_execute_ad_hoc_sql`

Fallback only. It accepts one read-only SELECT/CTE, applies an output row cap, rejects obvious write/admin operations, rejects explicit cross-database object references, and can restrict two-part object references to configured schemas. The Service Principal's Fabric permissions remain the real security boundary.

## Configuration

Copy `.env.example` to `.env` and fill in your real values.

Minimum required configuration:

```text
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=
FABRIC_SQL_ENDPOINT=
FABRIC_DATABASE=dwh_report
```

For MVD:

```text
FABRIC_TRANSFORM_DATABASE=lh_transform
```

If `lh_transform` has a different SQL endpoint, also set:

```text
FABRIC_TRANSFORM_SQL_ENDPOINT=
```

Do not distribute `.env`, put it in source control, or include it in a team ZIP.

## Install

Windows example:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
```

The unit tests do not require Fabric. The integration test does:

```bat
python tests\integration_test.py
```

## Claude Desktop

Use the absolute path to the virtual-environment Python executable and `server.py`. Start from `claude_desktop_config.example.json`.

```json
{
  "mcpServers": {
    "dsn-fabric-mcp": {
      "command": "C:\\your\\path\\.venv\\Scripts\\python.exe",
      "args": ["C:\\your\\path\\server.py"]
    }
  }
}
```

Restart Claude Desktop after changing the configuration.

## Skill

The optional skill is in:

```text
skill/dsn-fabric-analytics/
```

Its purpose is to teach Claude which MCP workflow to choose and how to interpret DSN terminology. It deliberately does **not** contain executable SQL. Calculation correctness stays in the MCP server.

## Business-rule ownership

Change `BUSINESS_RULE_VERSION` whenever you intentionally change a calculation rule. Every `dsn_query` result and every Excel export records this version.

Important rule locations:

- `business_rules.py` — approved lists, exclusions, methodology text/version
- `queries/*.sql` — server-owned SQL structure
- `query_builder.py` — date resolution, parameterized filters, report constraints

## Security notes

1. Give the Service Principal only read permissions required on the intended Fabric SQL endpoints.
2. Do not rely on `sql_validator.py` as the security boundary.
3. Do not expose endpoints, secrets, or target database selection as Claude tool parameters.
4. Keep ad-hoc SQL as a fallback; standard metrics should use `dsn_query`.

## Known operational limit

`FABRIC_MAX_RESULT_ROWS` defaults to 250,000 so a runaway detail pull does not fill local disk indefinitely. If a result hits the cap, the tool marks the dataset `truncated=true` and includes a warning. Increase the setting only after considering Excel's worksheet row limit and local-machine capacity.

## Local data retention

`runtime/results/` contains cached query rows as local JSONL until the TTL cleanup removes them, and `exports/` contains generated Excel extracts. These folders may contain business-sensitive data. Keep them on an appropriately secured workstation, do not sync them to an uncontrolled location, and adjust `FABRIC_RESULT_CACHE_TTL_HOURS` to your retention needs.
