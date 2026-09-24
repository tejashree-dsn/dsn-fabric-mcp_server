---
name: DSN Fabric Analytics
description: Use the DSN Fabric MCP to answer DSN transaction, revenue, agency, dealer-group, reference-summary, EOMV retail, and MVD questions using approved reconciliation methodology.
---

# DSN Fabric Analytics

Use the connected `dsn-fabric-mcp` as the authoritative execution layer for DSN Fabric analysis.

## Tool-selection rule

Use `dsn_query` first whenever one of its approved reports can answer the question. Do not recreate a standard DSN metric with ad-hoc SQL. Use `dsn_catalog` when an agency code, exact parent-customer name, table, column, or methodology must be resolved. Use `dsn_result` to page or export a result already produced by `dsn_query`. Use `dsn_execute_ad_hoc_sql` only when no approved report covers the request.

## Important calculation rules

For transaction counts, do not use physical fact row counts as the business transaction count. The approved workflows use `COUNT(DISTINCT transaction_id)` where appropriate because the Fabric fact can fan out a transaction through service rows.

For core transaction reconciliation, the approved definition is all EFS transactions plus non-EFS transactions whose upper-cased sub-service name is one of: ORIG NEW TITLE, TRANSFER TITLE, ORIG USED TITLE, ORIGINAL USED TITLE. The server returns `all_txns` beside `core_txns` as a control.

Use `agency_code` for agency filtering/mapping rather than trying to infer agency identity from `entity_name`.

Date windows use an inclusive lower bound and exclusive upper bound: `transaction_date >= from_date AND transaction_date < to_date`. Do not build two date ranges with `OR` to compare periods; run the approved report for the intended windows or use one continuous window and interpret the month field.

For authoritative total revenue by entity/source, use `aggregate_summary`. Do not derive authoritative revenue totals by summing a multi-dimension detail extract because joins can fan out revenue.

`DSNL` should not automatically be treated as missing data or an agency-code gap. It is a cube/service-line behavior documented in the DSN reconciliation work.

## Result handling

`dsn_query` returns a bounded preview and a `query_id`. If the full result is large, do not ask Fabric for it again. Use `dsn_result` with `action=page` to inspect additional rows or `action=export` to write the cached complete result to Excel.

If `parent_customer_detail` returns zero rows, use `dsn_catalog` with `action=list_parent_customers` and search for the intended name. Parent-customer matching is exact in the approved workflow.

When a result does not reconcile, report the variance and investigate scope/data vintage/mapping. Do not silently change filters or methodology just to force the number to match.

## Typical mappings

- "core transactions", "title transactions", dealer/agency transaction reconciliation -> `core_transactions`
- transaction-level records for a named dealer group -> `parent_customer_detail`
- transactions by dealer and service -> `dealer_service_summary`
- authoritative entity counts + source revenue -> `aggregate_summary`
- reference-workbook-shaped summary -> `reference_summary`
- EOMV retail -> `eomv_retail`
- MVD / lh_transform -> `mvd`

Read `references/methodology.md` when explaining why the numbers are calculated this way.
