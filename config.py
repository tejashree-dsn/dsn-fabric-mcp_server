"""Configuration for the DSN Fabric MCP server.

Secrets are loaded from a local .env file next to this module. The module never
logs or returns secret values. The Service Principal is the real Fabric/SQL
security boundary; application-side validation is defense in depth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
_ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required configuration: {name}. Set it in .env "
            f"(see .env.example)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}.")
    return value


@dataclass(frozen=True)
class FabricTarget:
    endpoint: str
    database: str
    label: str


@dataclass(frozen=True)
class FabricConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    warehouse_target: FabricTarget
    transform_target: FabricTarget | None
    workspace_id: str | None
    warehouse_id: str | None
    allowed_adhoc_schemas: tuple[str, ...]
    export_dir: Path
    result_cache_dir: Path
    connection_timeout_seconds: int
    query_timeout_seconds: int
    fetch_size: int
    max_result_rows: int
    max_adhoc_rows: int
    result_cache_ttl_hours: int
    default_preview_rows: int
    max_preview_rows: int


def load_config() -> FabricConfig:
    """Load and validate configuration without exposing secret values."""
    tenant_id = _required("FABRIC_TENANT_ID")
    client_id = _required("FABRIC_CLIENT_ID")
    client_secret = _required("FABRIC_CLIENT_SECRET")
    sql_endpoint = _required("FABRIC_SQL_ENDPOINT")
    database = _required("FABRIC_DATABASE")

    transform_endpoint = _optional("FABRIC_TRANSFORM_SQL_ENDPOINT") or sql_endpoint
    transform_database = _optional("FABRIC_TRANSFORM_DATABASE")
    transform_target = (
        FabricTarget(transform_endpoint, transform_database, "lh_transform")
        if transform_database
        else None
    )

    allowed = tuple(
        x.strip()
        for x in _optional("FABRIC_ADHOC_ALLOWED_SCHEMAS", "datamart").split(",")
        if x.strip()
    )
    if not allowed:
        raise ConfigError("FABRIC_ADHOC_ALLOWED_SCHEMAS must contain at least one schema.")

    export_dir = Path(_optional("FABRIC_EXPORT_DIR", str(BASE_DIR / "exports"))).expanduser()
    result_cache_dir = Path(
        _optional("FABRIC_RESULT_CACHE_DIR", str(BASE_DIR / "runtime" / "results"))
    ).expanduser()

    return FabricConfig(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        warehouse_target=FabricTarget(sql_endpoint, database, "dwh_report"),
        transform_target=transform_target,
        workspace_id=_optional("FABRIC_WORKSPACE_ID") or None,
        warehouse_id=_optional("FABRIC_WAREHOUSE_ID") or None,
        allowed_adhoc_schemas=allowed,
        export_dir=export_dir,
        result_cache_dir=result_cache_dir,
        connection_timeout_seconds=_int_env("FABRIC_CONNECTION_TIMEOUT_SECONDS", 30),
        query_timeout_seconds=_int_env("FABRIC_QUERY_TIMEOUT_SECONDS", 180),
        fetch_size=_int_env("FABRIC_FETCH_SIZE", 1000),
        max_result_rows=_int_env("FABRIC_MAX_RESULT_ROWS", 250_000),
        max_adhoc_rows=_int_env("FABRIC_MAX_ADHOC_ROWS", 2_000),
        result_cache_ttl_hours=_int_env("FABRIC_RESULT_CACHE_TTL_HOURS", 24),
        default_preview_rows=_int_env("FABRIC_DEFAULT_PREVIEW_ROWS", 100),
        max_preview_rows=_int_env("FABRIC_MAX_PREVIEW_ROWS", 500),
    )
