"""Central DSN business/reconciliation rules.

Keep business semantics here, not in Claude prompts. A skill can explain these
rules, but the MCP server is responsible for enforcing calculation logic.
"""

from __future__ import annotations

from typing import Any

from models import ReportType

BUSINESS_RULE_VERSION = "DSN_FABRIC_2026-08-10_V1"

CORE_NON_EFS_SUB_SERVICES = (
    "ORIG NEW TITLE",
    "TRANSFER TITLE",
    "ORIG USED TITLE",
    "ORIGINAL USED TITLE",
)

REF_KEEP_SOURCES = (
    "add123",
    "bc",
    "efs",
    "eltmanager",
    "eltv1",
    "inovah",
    "quickview",
    "square",
)

REF_EXCLUDE_ENTITIES = (
    "DEALER SERVICES NETWORK OF FLORIDA",
    "DEALER SERVICES NETWORK OF GEORGIA",
    "DEALER SERVICES NETWORK OF INDIANA",
    "Dealer Services Network of Texas",
    "Dealer Tag Agency",
    "Express OMV Alexandria Dealer",
    "Express OMV Bossier City Dealer",
    "Express OMV Houma Dealer",
    "Express OMV Lafayette Dealer",
    "Express OMV Lake Charles Prien Dealer",
    "Express OMV Metairie Dealer",
    "Express OMV Monroe Dealer",
    "Express OMV Slidell Dealer",
    "HialeahAuto Tag Agency",
    "JAV Auto Tag Agency",
)

AGG_EXCLUDE_ENTITIES = (
    "Auto Title Service Group",
    "Express OMV",
    "Dealer Services Network of North Texas",
)
AGG_EXCLUDE_SOURCES = ("atares",)

REPORT_CATALOG: dict[str, dict[str, Any]] = {
    ReportType.CORE_TRANSACTIONS.value: {
        "purpose": "Reconciliation-grade transaction counts using the proven EFS/non-EFS core-title rule.",
        "supports": ["agency_codes", "parent_customer", "grain", "date window"],
        "default_grain": "month_agency_parent_customer_dealer",
    },
    ReportType.PARENT_CUSTOMER_DETAIL.value: {
        "purpose": "Transaction-level detail for one exact parent customer.",
        "supports": ["parent_customer (required)", "agency_codes", "date window"],
    },
    ReportType.DEALER_SERVICE_SUMMARY.value: {
        "purpose": "Distinct transaction counts by parent customer, service and month.",
        "supports": ["parent_customer", "agency_codes", "date window"],
    },
    ReportType.AGGREGATE_SUMMARY.value: {
        "purpose": "Authoritative server-side entity transaction counts and source revenue summary.",
        "supports": ["date window", "include_all"],
    },
    ReportType.REFERENCE_SUMMARY.value: {
        "purpose": "Reference-workbook-shaped transaction-count and revenue summaries using the legacy reference scope.",
        "supports": ["agency_codes", "date window"],
    },
    ReportType.EOMV_RETAIL.value: {
        "purpose": "EOMV retail detail keyed by parent_entity_name + Express Lane for DMV, not agency_code.",
        "supports": ["date window"],
    },
    ReportType.MVD.value: {
        "purpose": "MVD transaction detail from lh_transform.mvd.transaction.",
        "supports": ["agency_codes", "date window"],
    },
}


def methodology_for(report: ReportType, *, include_all: bool = False) -> dict[str, Any]:
    common = {
        "business_rule_version": BUSINESS_RULE_VERSION,
        "date_semantics": "transaction_date >= from_date AND transaction_date < to_date (exclusive upper bound)",
    }

    if report == ReportType.CORE_TRANSACTIONS:
        return {
            **common,
            "transaction_count": "COUNT(DISTINCT transaction_id)",
            "efs_scope": "all EFS transactions",
            "non_efs_scope": list(CORE_NON_EFS_SUB_SERVICES),
            "case_handling": "UPPER(sub_service_name) before matching the approved non-EFS title list",
            "control_metric": "all_txns is always returned beside core_txns",
            "agency_dimension": "dim_entity.agency_code",
            "revenue_note": "Revenue mirrors the legacy core-final query. Use aggregate_summary for authoritative total revenue because detail/dimension joins can fan out revenue.",
        }

    if report == ReportType.PARENT_CUSTOMER_DETAIL:
        return {
            **common,
            "parent_match": "exact match on dim_parent_customer.parent_customer_name",
            "agency_dimension": "dim_entity.agency_code",
            "detail_grain": "transaction-level fact rows with service, vehicle, entity and customer dimensions",
        }

    if report == ReportType.DEALER_SERVICE_SUMMARY:
        return {
            **common,
            "transaction_count": "COUNT(DISTINCT transaction_id)",
            "grain": "parent customer x service x calendar month",
        }

    if report == ReportType.AGGREGATE_SUMMARY:
        return {
            **common,
            "entity_dataset": "fact_transaction + dim_entity; COUNT(DISTINCT transaction_id); applies entity and source exclusions unless include_all=true",
            "source_dataset": "fact_transaction only; SUM(revenue_amount); applies source exclusions only",
            "provisional_excluded_entities": [] if include_all else list(AGG_EXCLUDE_ENTITIES),
            "provisional_excluded_sources": [] if include_all else list(AGG_EXCLUDE_SOURCES),
            "important": "Do not derive these totals from the multi-dimension detail extract; the legacy build documented join fan-out overstatement.",
        }

    if report == ReportType.REFERENCE_SUMMARY:
        return {
            **common,
            "keep_sources_case_insensitive": list(REF_KEEP_SOURCES),
            "excluded_entities_case_insensitive": list(REF_EXCLUDE_ENTITIES),
            "transaction_count": "COUNT(DISTINCT transaction_id)",
            "revenue": "SUM(revenue_amount)",
        }

    if report == ReportType.EOMV_RETAIL:
        return {
            **common,
            "filter": "dim_entity.parent_entity_name = 'EOMV' AND dim_service.service_name = 'Express Lane for DMV'",
            "agency_note": "No agency_code filter; legacy logic documented agency_code as NULL for these retail rows.",
        }

    if report == ReportType.MVD:
        return {
            **common,
            "source": "lh_transform.mvd.transaction",
            "joins": "none; MVD dimensions used by this workflow are carried on the table",
        }

    return common
