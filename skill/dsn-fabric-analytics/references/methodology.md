# DSN Fabric methodology reference

The MCP server, not the model, owns the calculation rules. The skill should guide tool selection and interpretation only.

## Core transactions

EFS transactions count in full. Non-EFS transactions count toward the core measure only when `UPPER(sub_service_name)` is one of `ORIG NEW TITLE`, `TRANSFER TITLE`, `ORIG USED TITLE`, or `ORIGINAL USED TITLE`. Counts use distinct `transaction_id`. `all_txns` is retained as a control.

## Date semantics

All curated reports use inclusive start / exclusive end dates. A request for June 2026 resolves to `2026-06-01 <= transaction_date < 2026-07-01`.

## Aggregate summary

The entity dataset joins `fact_transaction` only to `dim_entity` and computes distinct transaction counts. The source-revenue dataset aggregates directly from `fact_transaction` and intentionally does not apply entity exclusions. This preserves the legacy reconciliation methodology.

## Reference summary

The reference workflow keeps only the configured source list and excludes the configured entity list using case-normalized comparisons. Both entity transaction count and revenue-by-source use that reference scope.

## Large outputs

The MCP writes results to a local disk-backed cache. Claude receives only a preview. `dsn_result` can page the cached rows or export an XLSX containing the result and a `_pull_info` provenance sheet.
