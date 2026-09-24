"""Typed MCP input/output models.

The MCP Python SDK derives JSON schemas from these Pydantic models so Claude
receives explicit enums, constraints, and structured results.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ReportType(str, Enum):
    CORE_TRANSACTIONS = "core_transactions"
    PARENT_CUSTOMER_DETAIL = "parent_customer_detail"
    DEALER_SERVICE_SUMMARY = "dealer_service_summary"
    AGGREGATE_SUMMARY = "aggregate_summary"
    REFERENCE_SUMMARY = "reference_summary"
    EOMV_RETAIL = "eomv_retail"
    MVD = "mvd"


class CoreGrain(str, Enum):
    MONTH = "month"
    MONTH_AGENCY = "month_agency"
    MONTH_PARENT_CUSTOMER = "month_parent_customer"
    MONTH_AGENCY_PARENT_CUSTOMER = "month_agency_parent_customer"
    MONTH_AGENCY_PARENT_CUSTOMER_DEALER = "month_agency_parent_customer_dealer"


class ResultMode(str, Enum):
    PREVIEW = "preview"
    EXPORT = "export"


class QueryRequest(BaseModel):
    report: ReportType = Field(description="Approved DSN report/workflow to run.")
    year: int | None = Field(default=None, ge=2000, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    months: list[int] | None = Field(
        default=None,
        description="Optional contiguous calendar months, e.g. [1,2,3].",
    )
    from_date: date | None = Field(
        default=None,
        description="Inclusive start date. Use together with to_date.",
    )
    to_date: date | None = Field(
        default=None,
        description="Exclusive end date. Use together with from_date.",
    )
    agency_codes: list[str] | None = Field(
        default=None,
        description="Optional exact agency_code values. Omit for all agencies.",
    )
    parent_customer: str | None = Field(
        default=None,
        description="Exact parent customer name when the report supports it.",
    )
    include_all: bool = Field(
        default=False,
        description="aggregate_summary only: disable provisional entity/source exclusions.",
    )
    grain: CoreGrain = Field(
        default=CoreGrain.MONTH_AGENCY_PARENT_CUSTOMER_DEALER,
        description="Grouping grain for core_transactions only.",
    )
    result_mode: ResultMode = Field(
        default=ResultMode.PREVIEW,
        description="preview returns bounded rows; export also writes an XLSX on the MCP host.",
    )
    preview_rows: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def validate_dates_and_months(self) -> "QueryRequest":
        if (self.from_date is None) ^ (self.to_date is None):
            raise ValueError("from_date and to_date must be supplied together.")
        if self.from_date and self.to_date and self.from_date >= self.to_date:
            raise ValueError("from_date must be earlier than to_date (to_date is exclusive).")
        if self.from_date and (self.month is not None or self.months):
            raise ValueError("Explicit from_date/to_date cannot be combined with month/months.")
        if self.month is not None and self.months:
            raise ValueError("Use either month or months, not both.")
        if not self.from_date and self.year is None:
            raise ValueError("year is required unless from_date/to_date are supplied.")
        if self.months:
            clean = sorted(set(self.months))
            if any(m < 1 or m > 12 for m in clean):
                raise ValueError("months must contain values from 1 to 12.")
            if clean != list(range(clean[0], clean[-1] + 1)):
                raise ValueError("months must be contiguous, e.g. [1,2,3].")
            self.months = clean
        if self.agency_codes:
            self.agency_codes = [x.strip().upper() for x in self.agency_codes if x.strip()]
            if not self.agency_codes:
                self.agency_codes = None
        if self.parent_customer is not None:
            self.parent_customer = self.parent_customer.strip() or None
        return self


class QueryScope(BaseModel):
    from_date: str
    to_date_exclusive: str
    agency_codes: list[str] | None = None
    parent_customer: str | None = None
    grain: str | None = None
    include_all: bool | None = None
    target: str = "dwh_report"


class DatasetSummary(BaseModel):
    name: str
    columns: list[str]
    row_count: int
    preview_rows: list[list[Any]]
    truncated: bool
    query_hash: str


class QueryResponse(BaseModel):
    query_id: str
    report: str
    business_rule_version: str
    scope: QueryScope
    methodology: dict[str, Any]
    datasets: list[DatasetSummary]
    warnings: list[str]
    execution_ms: int
    export_path: str | None = None
    export_uri: str | None = None


class CatalogAction(str, Enum):
    LIST_REPORTS = "list_reports"
    METHODOLOGY = "methodology"
    LIST_AGENCIES = "list_agencies"
    LIST_PARENT_CUSTOMERS = "list_parent_customers"
    LIST_TABLES = "list_tables"
    DESCRIBE_TABLE = "describe_table"
    SEARCH_COLUMNS = "search_columns"


class CatalogRequest(BaseModel):
    action: CatalogAction
    search: str | None = None
    report: ReportType | None = None
    schema_name: str | None = None
    table_name: str | None = None
    limit: int = Field(default=200, ge=1, le=500)


class CatalogResponse(BaseModel):
    action: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultAction(str, Enum):
    METADATA = "metadata"
    PAGE = "page"
    EXPORT = "export"


class ResultRequest(BaseModel):
    action: ResultAction
    query_id: str
    dataset: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ResultResponse(BaseModel):
    action: str
    query_id: str
    dataset: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    offset: int = 0
    returned_rows: int = 0
    total_rows: int = 0
    has_more: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    export_path: str | None = None
    export_uri: str | None = None


class AdHocResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    limit: int
    execution_ms: int
    warning: str


class HealthResponse(BaseModel):
    status: str
    warehouse: str
    connection: str
    transform_configured: bool
    detail: str | None = None
