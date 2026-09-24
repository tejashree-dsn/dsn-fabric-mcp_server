"""Pure query planning: converts approved typed requests into parameterized SQL."""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from business_rules import (
    AGG_EXCLUDE_ENTITIES,
    AGG_EXCLUDE_SOURCES,
    BUSINESS_RULE_VERSION,
    CORE_NON_EFS_SUB_SERVICES,
    REF_EXCLUDE_ENTITIES,
    REF_KEEP_SOURCES,
    methodology_for,
)
from models import CoreGrain, QueryRequest, QueryScope, ReportType

QUERY_DIR = Path(__file__).resolve().parent / "queries"


class QueryBuildError(Exception):
    pass


@dataclass(frozen=True)
class DatasetPlan:
    name: str
    template_name: str
    sql: str
    params: tuple[Any, ...]
    target: str = "warehouse"

    @property
    def query_hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.sql.encode("utf-8"))
        digest.update(repr(self.params).encode("utf-8"))
        return digest.hexdigest()


@dataclass(frozen=True)
class QueryPlan:
    report: ReportType
    business_rule_version: str
    scope: QueryScope
    methodology: dict[str, Any]
    datasets: tuple[DatasetPlan, ...]
    warnings: tuple[str, ...]


def _load_template(name: str) -> str:
    path = QUERY_DIR / name
    if not path.exists():
        raise QueryBuildError(f"Server query template is missing: {name}")
    return path.read_text(encoding="utf-8")


def _render(template_name: str, replacements: dict[str, str]) -> str:
    text = _load_template(template_name)
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[A-Z0-9_]+\}\}", text):
        raise QueryBuildError(f"Unresolved server template token in {template_name}.")
    return text


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


def resolve_window(req: QueryRequest) -> tuple[date, date]:
    if req.from_date and req.to_date:
        return req.from_date, req.to_date
    assert req.year is not None
    if req.month is not None:
        return date(req.year, req.month, 1), _next_month(req.year, req.month)
    if req.months:
        start_m, end_m = min(req.months), max(req.months)
        return date(req.year, start_m, 1), _next_month(req.year, end_m)
    return date(req.year, 1, 1), date(req.year + 1, 1, 1)


def _placeholders(values: list[Any] | tuple[Any, ...]) -> str:
    return ", ".join("?" for _ in values)


def _agency_filter(column: str, agency_codes: list[str] | None) -> tuple[str, list[Any]]:
    if not agency_codes:
        return "", []
    return f"\n  AND {column} IN ({_placeholders(agency_codes)})", list(agency_codes)


def _parent_filter(column: str, parent: str | None) -> tuple[str, list[Any]]:
    if not parent:
        return "", []
    return f"\n  AND {column} = ?", [parent]


def _scope(req: QueryRequest, start: date, upper: date, target: str = "dwh_report") -> QueryScope:
    return QueryScope(
        from_date=start.isoformat(),
        to_date_exclusive=upper.isoformat(),
        agency_codes=req.agency_codes,
        parent_customer=req.parent_customer,
        grain=req.grain.value if req.report == ReportType.CORE_TRANSACTIONS else None,
        include_all=req.include_all if req.report == ReportType.AGGREGATE_SUMMARY else None,
        target=target,
    )


def _validate_report_options(req: QueryRequest) -> None:
    if req.report == ReportType.PARENT_CUSTOMER_DETAIL and not req.parent_customer:
        raise QueryBuildError("parent_customer_detail requires parent_customer.")
    if req.report in {ReportType.AGGREGATE_SUMMARY, ReportType.EOMV_RETAIL}:
        if req.agency_codes:
            raise QueryBuildError(f"{req.report.value} does not accept agency_codes; its methodology is fixed.")
        if req.parent_customer:
            raise QueryBuildError(f"{req.report.value} does not accept parent_customer; its methodology is fixed.")
    if req.report == ReportType.REFERENCE_SUMMARY and req.parent_customer:
        raise QueryBuildError("reference_summary does not accept parent_customer because that would change the reference methodology.")
    if req.report == ReportType.MVD and req.parent_customer:
        raise QueryBuildError("mvd does not have a parent_customer field in the approved workflow.")
    if req.include_all and req.report != ReportType.AGGREGATE_SUMMARY:
        raise QueryBuildError("include_all is only valid for aggregate_summary.")


def _core_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    dimensions = {
        CoreGrain.MONTH: [
            ("CONVERT(char(7), t.transaction_date, 126)", "ym"),
        ],
        CoreGrain.MONTH_AGENCY: [
            ("CONVERT(char(7), t.transaction_date, 126)", "ym"),
            ("e.agency_code", "agency_code"),
            ("e.entity_name", "entity_name"),
        ],
        CoreGrain.MONTH_PARENT_CUSTOMER: [
            ("CONVERT(char(7), t.transaction_date, 126)", "ym"),
            ("pc.parent_customer_name", "dealer_group"),
        ],
        CoreGrain.MONTH_AGENCY_PARENT_CUSTOMER: [
            ("CONVERT(char(7), t.transaction_date, 126)", "ym"),
            ("e.agency_code", "agency_code"),
            ("e.entity_name", "entity_name"),
            ("pc.parent_customer_name", "dealer_group"),
        ],
        CoreGrain.MONTH_AGENCY_PARENT_CUSTOMER_DEALER: [
            ("CONVERT(char(7), t.transaction_date, 126)", "ym"),
            ("e.agency_code", "agency_code"),
            ("e.entity_name", "entity_name"),
            ("pc.parent_customer_name", "dealer_group"),
            ("c.customer_name", "dealer_name"),
            ("c.customer_license_number", "dealer_license"),
        ],
    }[req.grain]

    dim_select = "\n".join(f"      {expr} AS {alias}," for expr, alias in dimensions)
    dim_group = ",\n      ".join(expr for expr, _ in dimensions)
    order_by = ", ".join(alias for _, alias in dimensions)

    filters = ""
    agency_sql, agency_params = _agency_filter("e.agency_code", req.agency_codes)
    parent_sql, parent_params = _parent_filter("pc.parent_customer_name", req.parent_customer)
    filters += agency_sql + parent_sql

    core_values = list(CORE_NON_EFS_SUB_SERVICES)
    core_in = _placeholders(core_values)
    # Parameter order must match appearance in SQL: the two CASE expressions
    # occur before the WHERE date/filter parameters.
    params: list[Any] = core_values + core_values + [start, upper]
    params.extend(agency_params)
    params.extend(parent_params)

    sql = _render(
        "core_transactions.sql",
        {
            "DIM_SELECT": dim_select,
            "CORE_SUBSERVICE_PLACEHOLDERS": core_in,
            "FILTERS": filters,
            "DIM_GROUP": dim_group,
            "ORDER_BY": order_by,
        },
    )

    warnings = (
        "For authoritative total revenue use aggregate_summary; the legacy build documented revenue fan-out risk when totals are derived from the multi-dimension detail path.",
    )
    return QueryPlan(
        report=req.report,
        business_rule_version=BUSINESS_RULE_VERSION,
        scope=_scope(req, start, upper),
        methodology=methodology_for(req.report),
        datasets=(DatasetPlan("core_transactions", "core_transactions.sql", sql, tuple(params)),),
        warnings=warnings,
    )


def _parent_detail_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    filters = "\n  AND pc.parent_customer_name = ?"
    params: list[Any] = [start, upper, req.parent_customer]
    agency_sql, agency_params = _agency_filter("e.agency_code", req.agency_codes)
    filters += agency_sql
    params.extend(agency_params)
    sql = _render("parent_customer_detail.sql", {"FILTERS": filters})
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper),
        methodology_for(req.report),
        (DatasetPlan("parent_customer_detail", "parent_customer_detail.sql", sql, tuple(params)),),
        (),
    )


def _dealer_service_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    filters = ""
    params: list[Any] = [start, upper]
    parent_sql, parent_params = _parent_filter("c.parent_customer_name", req.parent_customer)
    agency_sql, agency_params = _agency_filter("e.agency_code", req.agency_codes)
    filters += parent_sql + agency_sql
    params.extend(parent_params)
    params.extend(agency_params)
    sql = _render("dealer_service_summary.sql", {"FILTERS": filters})
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper),
        methodology_for(req.report),
        (DatasetPlan("dealer_service_summary", "dealer_service_summary.sql", sql, tuple(params)),),
        (),
    )


def _aggregate_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    exclude_entities = [] if req.include_all else list(AGG_EXCLUDE_ENTITIES)
    exclude_sources = [] if req.include_all else list(AGG_EXCLUDE_SOURCES)

    filters1 = ""
    params1: list[Any] = [start, upper]
    if exclude_entities:
        filters1 += f"\n  AND e.entity_name NOT IN ({_placeholders(exclude_entities)})"
        params1.extend(exclude_entities)
    if exclude_sources:
        filters1 += f"\n  AND t.source NOT IN ({_placeholders(exclude_sources)})"
        params1.extend(exclude_sources)

    filters2 = ""
    params2: list[Any] = [start, upper]
    if exclude_sources:
        filters2 += f"\n  AND t.source NOT IN ({_placeholders(exclude_sources)})"
        params2.extend(exclude_sources)

    q1 = _render("aggregate_entity.sql", {"FILTERS": filters1})
    q2 = _render("aggregate_source.sql", {"FILTERS": filters2})
    warnings = () if req.include_all else (
        "aggregate_summary uses the legacy provisional entity/source exclusion lists. Set include_all=true to disable them for a comparison run.",
    )
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper),
        methodology_for(req.report, include_all=req.include_all),
        (
            DatasetPlan("Transaction Count by Entity", "aggregate_entity.sql", q1, tuple(params1)),
            DatasetPlan("Revenue by Source", "aggregate_source.sql", q2, tuple(params2)),
        ),
        warnings,
    )


def _reference_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    keep = list(REF_KEEP_SOURCES)
    exclude = [x.strip().upper() for x in REF_EXCLUDE_ENTITIES]
    common = (
        f"\n  AND LOWER(LTRIM(RTRIM(t.source))) IN ({_placeholders(keep)})"
        f"\n  AND (e.entity_name IS NULL OR UPPER(LTRIM(RTRIM(e.entity_name))) NOT IN ({_placeholders(exclude)}))"
    )
    agency_sql, agency_params = _agency_filter("e.agency_code", req.agency_codes)
    filters = common + agency_sql
    base_params: list[Any] = [start, upper] + keep + exclude + agency_params

    q1 = _render("reference_entity.sql", {"FILTERS": filters})
    q2 = _render("reference_source.sql", {"FILTERS": filters})
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper),
        methodology_for(req.report),
        (
            DatasetPlan("Transaction Count by Entity", "reference_entity.sql", q1, tuple(base_params)),
            DatasetPlan("Revenue by Source", "reference_source.sql", q2, tuple(base_params)),
        ),
        (),
    )


def _eomv_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    sql = _load_template("eomv_retail.sql")
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper),
        methodology_for(req.report),
        (DatasetPlan("eomv_retail", "eomv_retail.sql", sql, (start, upper)),),
        (),
    )


def _mvd_plan(req: QueryRequest, start: date, upper: date) -> QueryPlan:
    filters = ""
    params: list[Any] = [start, upper]
    agency_sql, agency_params = _agency_filter("agency_code", req.agency_codes)
    filters += agency_sql
    params.extend(agency_params)
    sql = _render("mvd.sql", {"FILTERS": filters})
    return QueryPlan(
        req.report,
        BUSINESS_RULE_VERSION,
        _scope(req, start, upper, target="lh_transform"),
        methodology_for(req.report),
        (DatasetPlan("mvd_transactions", "mvd.sql", sql, tuple(params), target="transform"),),
        (),
    )


def build_query_plan(req: QueryRequest) -> QueryPlan:
    _validate_report_options(req)
    start, upper = resolve_window(req)

    if req.report == ReportType.CORE_TRANSACTIONS:
        return _core_plan(req, start, upper)
    if req.report == ReportType.PARENT_CUSTOMER_DETAIL:
        return _parent_detail_plan(req, start, upper)
    if req.report == ReportType.DEALER_SERVICE_SUMMARY:
        return _dealer_service_plan(req, start, upper)
    if req.report == ReportType.AGGREGATE_SUMMARY:
        return _aggregate_plan(req, start, upper)
    if req.report == ReportType.REFERENCE_SUMMARY:
        return _reference_plan(req, start, upper)
    if req.report == ReportType.EOMV_RETAIL:
        return _eomv_plan(req, start, upper)
    if req.report == ReportType.MVD:
        return _mvd_plan(req, start, upper)
    raise QueryBuildError(f"Unsupported report: {req.report}")
