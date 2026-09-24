"""Manual integration test. Requires real .env, pyodbc and ODBC Driver 18."""

from __future__ import annotations

from config import ConfigError, load_config
from fabric_client import FabricClient
from models import QueryRequest, ReportType
from query_builder import build_query_plan


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("NOT RUN: configuration unavailable")
        print(exc)
        return 0

    client = FabricClient(cfg)
    health = client.health_check()
    print("health:", health)
    if health["status"] != "ok":
        return 1

    plan = build_query_plan(
        QueryRequest(report=ReportType.CORE_TRANSACTIONS, year=2026, month=6)
    )
    ds = plan.datasets[0]
    result = client.execute_query(ds.sql, ds.params, max_rows=5)
    print("core_transactions preview:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
