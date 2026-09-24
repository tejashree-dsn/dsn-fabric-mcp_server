"""Targeted catalog discovery for Claude; avoids dumping the whole warehouse schema."""

from __future__ import annotations

import re
from typing import Any

from business_rules import REPORT_CATALOG, methodology_for
from fabric_client import FabricClient
from models import CatalogAction, CatalogRequest, CatalogResponse


class CatalogError(Exception):
    pass


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CatalogService:
    def __init__(self, client: FabricClient) -> None:
        self.client = client

    def run(self, request: CatalogRequest) -> CatalogResponse:
        if request.action == CatalogAction.LIST_REPORTS:
            rows = [[name, value["purpose"], ", ".join(value["supports"])] for name, value in REPORT_CATALOG.items()]
            return CatalogResponse(
                action=request.action.value,
                columns=["report", "purpose", "supports"],
                rows=rows,
                row_count=len(rows),
                metadata={"use": "Prefer dsn_query for these approved workflows."},
            )

        if request.action == CatalogAction.METHODOLOGY:
            if request.report:
                method = methodology_for(request.report)
                rows = [[k, str(v)] for k, v in method.items()]
                return CatalogResponse(
                    action=request.action.value,
                    columns=["rule", "value"],
                    rows=rows,
                    row_count=len(rows),
                    metadata={"report": request.report.value},
                )
            rows = [[name, value["purpose"]] for name, value in REPORT_CATALOG.items()]
            return CatalogResponse(
                action=request.action.value,
                columns=["report", "purpose"],
                rows=rows,
                row_count=len(rows),
                metadata={"hint": "Pass report to retrieve its detailed methodology."},
            )

        if request.action == CatalogAction.LIST_AGENCIES:
            where = "WHERE agency_code IS NOT NULL"
            params: list[Any] = []
            if request.search:
                where += " AND (agency_code LIKE ? OR entity_name LIKE ? OR parent_entity_name LIKE ?)"
                pattern = f"%{request.search}%"
                params.extend([pattern, pattern, pattern])
            sql = f"""
                SELECT DISTINCT agency_code, entity_name, parent_entity_name
                FROM [datamart].[dim_entity]
                {where}
                ORDER BY agency_code, entity_name
            """
            return self._query_response(request, sql, params)

        if request.action == CatalogAction.LIST_PARENT_CUSTOMERS:
            where = "WHERE parent_customer_name IS NOT NULL"
            params = []
            if request.search:
                where += " AND parent_customer_name LIKE ?"
                params.append(f"%{request.search}%")
            sql = f"""
                SELECT DISTINCT parent_customer_name
                FROM [datamart].[dim_parent_customer]
                {where}
                ORDER BY parent_customer_name
            """
            return self._query_response(request, sql, params)

        if request.action == CatalogAction.LIST_TABLES:
            sql = """
                SELECT TABLE_SCHEMA, TABLE_NAME, COUNT(*) AS column_count
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
                GROUP BY TABLE_SCHEMA, TABLE_NAME
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
            return self._query_response(request, sql, [])

        if request.action == CatalogAction.DESCRIBE_TABLE:
            schema = (request.schema_name or "").strip()
            table = (request.table_name or "").strip()
            if not (_IDENT.fullmatch(schema) and _IDENT.fullmatch(table)):
                raise CatalogError("describe_table requires valid schema_name and table_name identifiers.")
            sql = """
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """
            response = self._query_response(request, sql, [schema, table])
            response.metadata = {"schema": schema, "table": table}
            return response

        if request.action == CatalogAction.SEARCH_COLUMNS:
            if not request.search:
                raise CatalogError("search_columns requires search text.")
            pattern = f"%{request.search}%"
            sql = """
                SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
                  AND (COLUMN_NAME LIKE ? OR TABLE_NAME LIKE ?)
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
            return self._query_response(request, sql, [pattern, pattern])

        raise CatalogError(f"Unsupported catalog action: {request.action}")

    def _query_response(self, request: CatalogRequest, sql: str, params: list[Any]) -> CatalogResponse:
        result = self.client.execute_query(sql, params, max_rows=request.limit)
        return CatalogResponse(
            action=request.action.value,
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            truncated=result["truncated"],
        )
