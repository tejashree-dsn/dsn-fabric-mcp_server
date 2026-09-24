"""Microsoft Fabric SQL client using a Microsoft Entra Service Principal."""

from __future__ import annotations

import datetime
import decimal
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import pyodbc
from azure.identity import ClientSecretCredential

from config import FabricConfig, FabricTarget

logger = logging.getLogger("dsn_fabric_mcp.fabric_client")

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
TOKEN_SCOPE = "https://database.windows.net/.default"
SQL_COPT_SS_ACCESS_TOKEN = 1256
TOKEN_REFRESH_MARGIN_SECONDS = 120


class FabricConnectionError(Exception):
    pass


class FabricQueryError(Exception):
    pass


def serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value)


@dataclass(frozen=True)
class StreamExecution:
    columns: list[str]
    row_count: int
    truncated: bool
    duration_seconds: float


class FabricClient:
    """Connects only to server-configured Fabric targets.

    Claude never supplies an endpoint, database, credential, or token.
    """

    def __init__(self, config: FabricConfig) -> None:
        self._config = config
        self._credential = ClientSecretCredential(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )
        self._cached_token: str | None = None
        self._cached_token_expires_at = 0.0

    @property
    def config(self) -> FabricConfig:
        return self._config

    def _get_access_token_struct(self) -> bytes:
        now = time.time()
        if (
            not self._cached_token
            or now >= self._cached_token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS
        ):
            try:
                token = self._credential.get_token(TOKEN_SCOPE)
            except Exception as exc:
                raise FabricConnectionError(
                    "Service Principal authentication failed. Verify the configured "
                    "tenant/client/secret and Fabric permissions."
                ) from exc
            self._cached_token = token.token
            self._cached_token_expires_at = token.expires_on

        token_bytes = self._cached_token.encode("utf-16-le")
        return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    def _resolve_target(self, target: str) -> FabricTarget:
        if target == "warehouse":
            return self._config.warehouse_target
        if target == "transform":
            if self._config.transform_target is None:
                raise FabricConnectionError(
                    "The MVD/lh_transform target is not configured. Set "
                    "FABRIC_TRANSFORM_DATABASE (and optionally "
                    "FABRIC_TRANSFORM_SQL_ENDPOINT)."
                )
            return self._config.transform_target
        raise FabricConnectionError(f"Unknown server-configured target: {target}")

    def _connect(self, target: str = "warehouse") -> pyodbc.Connection:
        resolved = self._resolve_target(target)
        token_struct = self._get_access_token_struct()
        conn_str = (
            f"Driver={{{ODBC_DRIVER}}};"
            f"Server={resolved.endpoint};"
            f"Database={resolved.database};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            f"Connection Timeout={self._config.connection_timeout_seconds};"
        )
        try:
            return pyodbc.connect(
                conn_str,
                attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct},
                autocommit=True,
                timeout=self._config.connection_timeout_seconds,
            )
        except pyodbc.InterfaceError as exc:
            raise FabricConnectionError(
                f"Could not load '{ODBC_DRIVER}'. Install Microsoft ODBC Driver 18 "
                "for SQL Server and retry."
            ) from exc
        except pyodbc.Error as exc:
            raise FabricConnectionError(
                f"Could not connect to configured Fabric target '{resolved.database}'. "
                "Verify the SQL endpoint and Service Principal permissions."
            ) from exc

    def execute_stream(
        self,
        sql: str,
        params: Sequence[Any] | None,
        on_batch: Callable[[list[list[Any]]], None],
        *,
        target: str = "warehouse",
        max_rows: int | None = None,
    ) -> StreamExecution:
        """Execute SQL and stream JSON-safe row batches to a callback.

        If max_rows is reached, one additional row is probed so `truncated` is
        accurate when the result contains more rows than the configured cap.
        """
        conn = self._connect(target)
        started = time.monotonic()
        try:
            cursor = conn.cursor()
            try:
                try:
                    cursor.timeout = self._config.query_timeout_seconds
                except Exception:
                    # Some pyodbc/driver combinations do not expose cursor timeout.
                    pass
                try:
                    cursor.execute(sql, *(params or ()))
                except pyodbc.Error as exc:
                    raise FabricQueryError(f"Query failed: {exc}") from exc

                if cursor.description is None:
                    return StreamExecution([], 0, False, time.monotonic() - started)

                columns = [col[0] for col in cursor.description]
                total = 0
                truncated = False

                while True:
                    if max_rows is None:
                        fetch_n = self._config.fetch_size
                    else:
                        remaining = max_rows - total
                        # If exactly at the cap, probe one row to determine whether
                        # there is more data without storing it.
                        fetch_n = 1 if remaining <= 0 else min(self._config.fetch_size, remaining + 1)

                    try:
                        batch_raw = cursor.fetchmany(fetch_n)
                    except pyodbc.Error as exc:
                        raise FabricQueryError(f"Query fetch failed: {exc}") from exc
                    if not batch_raw:
                        break

                    batch = [[serialize_value(v) for v in row] for row in batch_raw]
                    if max_rows is not None and total + len(batch) > max_rows:
                        allowed = max_rows - total
                        if allowed > 0:
                            on_batch(batch[:allowed])
                            total += allowed
                        truncated = True
                        break

                    on_batch(batch)
                    total += len(batch)

                return StreamExecution(
                    columns=columns,
                    row_count=total,
                    truncated=truncated,
                    duration_seconds=time.monotonic() - started,
                )
            finally:
                cursor.close()
        finally:
            conn.close()

    def execute_query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        *,
        target: str = "warehouse",
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        rows: list[list[Any]] = []
        execution = self.execute_stream(
            sql,
            params,
            rows.extend,
            target=target,
            max_rows=max_rows,
        )
        return {
            "columns": execution.columns,
            "rows": rows,
            "row_count": execution.row_count,
            "truncated": execution.truncated,
            "duration_seconds": execution.duration_seconds,
        }

    def health_check(self) -> dict[str, Any]:
        target = self._config.warehouse_target
        try:
            result = self.execute_query("SELECT 1 AS ok", max_rows=1)
        except (FabricConnectionError, FabricQueryError) as exc:
            return {
                "status": "error",
                "warehouse": target.database,
                "connection": "failed",
                "transform_configured": self._config.transform_target is not None,
                "detail": str(exc),
            }
        if result["rows"] != [[1]]:
            return {
                "status": "error",
                "warehouse": target.database,
                "connection": "failed",
                "transform_configured": self._config.transform_target is not None,
                "detail": "Unexpected response from Fabric Warehouse.",
            }
        return {
            "status": "ok",
            "warehouse": target.database,
            "connection": "successful",
            "transform_configured": self._config.transform_target is not None,
            "detail": None,
        }
