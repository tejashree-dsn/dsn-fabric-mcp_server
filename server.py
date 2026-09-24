"""DSN Fabric MCP server for Claude Desktop.

Design principle:
- Claude decides WHAT approved analysis is needed.
- The MCP server deterministically decides HOW that analysis is calculated.
- Raw SQL is an explicitly-labelled fallback, not the primary workflow.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from catalog_service import CatalogError, CatalogService
from config import ConfigError, FabricConfig, load_config
from exporter import ExportError, export_query_to_xlsx
from fabric_client import FabricClient, FabricConnectionError, FabricQueryError
from models import (
    AdHocResponse,
    CatalogRequest,
    CatalogResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    ResultAction,
    ResultRequest,
    ResultResponse,
)
from query_builder import QueryBuildError
from query_service import QueryService
from result_store import ResultStore, ResultStoreError
from sql_validator import SQLValidationError, validate_select_only

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("dsn_fabric_mcp.server")

mcp = MCPServer(name="dsn-fabric-mcp")

_config: FabricConfig | None = None
_client: FabricClient | None = None
_store: ResultStore | None = None
_query_service: QueryService | None = None
_catalog_service: CatalogService | None = None


def _services() -> tuple[FabricConfig, FabricClient, ResultStore, QueryService, CatalogService]:
    global _config, _client, _store, _query_service, _catalog_service
    if _config is None:
        _config = load_config()
    if _client is None:
        _client = FabricClient(_config)
    if _store is None:
        _store = ResultStore(_config.result_cache_dir, _config.result_cache_ttl_hours)
    if _query_service is None:
        _query_service = QueryService(_config, _client, _store)
    if _catalog_service is None:
        _catalog_service = CatalogService(_client)
    return _config, _client, _store, _query_service, _catalog_service


def _tool_error(exc: Exception) -> ToolError:
    return ToolError(str(exc))


@mcp.tool(
    title="Run approved DSN Fabric analysis",
    description=(
        "Primary DSN analytics tool. Use this BEFORE ad-hoc SQL for standard transaction, "
        "revenue, agency, dealer-group, reference, EOMV or MVD questions. Business rules, "
        "COUNT(DISTINCT transaction_id), date semantics, service filters, exclusions and "
        "approved SQL are enforced server-side. Returns a bounded preview plus query_id; "
        "large results stay in the local result cache and can be paged/exported with dsn_result."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    structured_output=True,
)
def dsn_query(request: QueryRequest) -> QueryResponse:
    try:
        _, _, _, service, _ = _services()
        result = service.run(request)
        logger.info("dsn_query report=%s query_id=%s", result.report, result.query_id)
        return result
    except (
        ConfigError,
        FabricConnectionError,
        FabricQueryError,
        QueryBuildError,
        ResultStoreError,
        ExportError,
    ) as exc:
        raise _tool_error(exc) from exc


@mcp.tool(
    title="Browse DSN Fabric catalog",
    description=(
        "Use for targeted discovery: approved reports/methodology, valid agency codes, exact "
        "parent-customer names, tables, table columns, or column searches. Prefer this over "
        "dumping the entire warehouse schema into context."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    structured_output=True,
)
def dsn_catalog(request: CatalogRequest) -> CatalogResponse:
    try:
        _, _, _, _, service = _services()
        return service.run(request)
    except (ConfigError, FabricConnectionError, FabricQueryError, CatalogError) as exc:
        raise _tool_error(exc) from exc


@mcp.tool(
    title="Page or export a DSN query result",
    description=(
        "Use after dsn_query. action=page retrieves a bounded slice from the local result cache; "
        "action=metadata returns provenance; action=export writes the complete cached result to "
        "an XLSX with a _pull_info sheet. Do not re-query Fabric merely to see the next rows."
    ),
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    structured_output=True,
)
def dsn_result(request: ResultRequest) -> ResultResponse:
    try:
        config, _, store, _, _ = _services()
        meta = store.get_metadata(request.query_id)

        if request.action == ResultAction.METADATA:
            return ResultResponse(
                action=request.action.value,
                query_id=request.query_id,
                metadata=meta,
                export_path=meta.get("export_path"),
                export_uri=meta.get("export_uri"),
            )

        if request.action == ResultAction.EXPORT:
            path = export_query_to_xlsx(store, request.query_id, config.export_dir)
            return ResultResponse(
                action=request.action.value,
                query_id=request.query_id,
                metadata=store.get_metadata(request.query_id),
                export_path=str(path),
                export_uri=path.resolve().as_uri(),
            )

        datasets = meta.get("datasets", {})
        dataset = request.dataset
        if not dataset:
            if len(datasets) == 1:
                dataset = next(iter(datasets))
            else:
                raise ResultStoreError(
                    "This query has multiple datasets. Specify dataset exactly as listed in metadata."
                )
        page = store.get_page(
            request.query_id,
            dataset,
            offset=request.offset,
            limit=request.limit,
        )
        return ResultResponse(
            action=request.action.value,
            query_id=request.query_id,
            dataset=dataset,
            columns=page["columns"],
            rows=page["rows"],
            offset=page["offset"],
            returned_rows=page["returned_rows"],
            total_rows=page["total_rows"],
            has_more=page["has_more"],
            metadata={"truncated": page["truncated"]},
        )
    except (ConfigError, ResultStoreError, ExportError) as exc:
        raise _tool_error(exc) from exc


@mcp.tool(
    title="Run fallback read-only SQL",
    description=(
        "Fallback only. Use when no approved dsn_query report can answer the question. Executes a "
        "single read-only SELECT/CTE against the configured dwh_report warehouse, with an output "
        "row cap and defense-in-depth schema validation. Never use this to recreate a standard "
        "DSN metric that dsn_query already implements."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    structured_output=True,
)
def dsn_execute_ad_hoc_sql(sql: str, limit: int = 200) -> AdHocResponse:
    try:
        config, client, _, _, _ = _services()
        if limit < 1 or limit > config.max_adhoc_rows:
            raise SQLValidationError(
                f"limit must be between 1 and FABRIC_MAX_ADHOC_ROWS={config.max_adhoc_rows}."
            )
        validate_select_only(sql, config.allowed_adhoc_schemas)
        started = time.monotonic()
        result = client.execute_query(sql, max_rows=limit)
        return AdHocResponse(
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            truncated=result["truncated"],
            limit=limit,
            execution_ms=int((time.monotonic() - started) * 1000),
            warning="Ad-hoc SQL is a fallback. Standard DSN metrics should use dsn_query so server-owned methodology is enforced.",
        )
    except (ConfigError, SQLValidationError, FabricConnectionError, FabricQueryError) as exc:
        raise _tool_error(exc) from exc


@mcp.tool(
    title="Check DSN Fabric connectivity",
    description="Check configuration, Service Principal authentication and dwh_report connectivity. Returns no secrets or tokens.",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
    structured_output=True,
)
def health_check() -> HealthResponse:
    try:
        _, client, _, _, _ = _services()
        return HealthResponse(**client.health_check())
    except ConfigError as exc:
        return HealthResponse(
            status="error",
            warehouse="unknown",
            connection="not_attempted",
            transform_configured=False,
            detail=str(exc),
        )


if __name__ == "__main__":
    logger.info("Starting dsn-fabric-mcp (stdio transport)")
    mcp.run(transport="stdio")
