"""Execution service for approved DSN query plans."""

from __future__ import annotations

import time
from typing import Any

from config import FabricConfig
from exporter import export_query_to_xlsx
from fabric_client import FabricClient
from models import DatasetSummary, QueryRequest, QueryResponse, ResultMode
from query_builder import build_query_plan
from result_store import ResultStore


class QueryService:
    def __init__(
        self,
        config: FabricConfig,
        client: FabricClient,
        store: ResultStore,
    ) -> None:
        self.config = config
        self.client = client
        self.store = store

    def run(self, request: QueryRequest) -> QueryResponse:
        plan = build_query_plan(request)
        preview_limit = min(request.preview_rows, self.config.max_preview_rows)
        started = time.monotonic()

        query_id = self.store.create_query(
            {
                "report": plan.report.value,
                "business_rule_version": plan.business_rule_version,
                "scope": plan.scope.model_dump(),
                "methodology": plan.methodology,
                "warnings": list(plan.warnings),
            }
        )

        summaries: list[DatasetSummary] = []
        warnings = list(plan.warnings)

        try:
            for dataset in plan.datasets:
                self.store.begin_dataset(
                    query_id,
                    dataset.name,
                    template_name=dataset.template_name,
                    query_hash=dataset.query_hash,
                )
                preview: list[list[Any]] = []

                def on_batch(rows: list[list[Any]]) -> None:
                    self.store.append_rows(query_id, dataset.name, rows)
                    if len(preview) < preview_limit:
                        remaining = preview_limit - len(preview)
                        preview.extend(rows[:remaining])

                execution = self.client.execute_stream(
                    dataset.sql,
                    dataset.params,
                    on_batch,
                    target=dataset.target,
                    max_rows=self.config.max_result_rows,
                )
                self.store.finalize_dataset(
                    query_id,
                    dataset.name,
                    columns=execution.columns,
                    row_count=execution.row_count,
                    truncated=execution.truncated,
                )
                if execution.truncated:
                    warnings.append(
                        f"Dataset '{dataset.name}' hit FABRIC_MAX_RESULT_ROWS="
                        f"{self.config.max_result_rows:,}; cached/exported data is truncated."
                    )
                summaries.append(
                    DatasetSummary(
                        name=dataset.name,
                        columns=execution.columns,
                        row_count=execution.row_count,
                        preview_rows=preview,
                        truncated=execution.truncated,
                        query_hash=dataset.query_hash,
                    )
                )
        except Exception:
            # Failed partial caches are more confusing than useful.
            self.store.delete_query(query_id)
            raise

        if (
            request.report.value == "parent_customer_detail"
            and summaries
            and summaries[0].row_count == 0
        ):
            warnings.append(
                "The exact parent_customer match returned 0 rows. Use dsn_catalog "
                "action=list_parent_customers to verify the stored spelling/casing."
            )

        # Persist warnings BEFORE any export so _pull_info gets the same provenance
        # that Claude receives.
        self.store.update_metadata(query_id, warnings=warnings)

        export_path = None
        export_uri = None
        if request.result_mode == ResultMode.EXPORT:
            path = export_query_to_xlsx(self.store, query_id, self.config.export_dir)
            export_path = str(path)
            export_uri = path.resolve().as_uri()

        return QueryResponse(
            query_id=query_id,
            report=plan.report.value,
            business_rule_version=plan.business_rule_version,
            scope=plan.scope,
            methodology=plan.methodology,
            datasets=summaries,
            warnings=warnings,
            execution_ms=int((time.monotonic() - started) * 1000),
            export_path=export_path,
            export_uri=export_uri,
        )
