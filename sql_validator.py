"""Defense-in-depth validation for the ad-hoc SELECT tool.

This is deliberately not treated as the authorization boundary. The configured
Service Principal must have read-only access to only the intended Fabric data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "DENY", "MERGE", "EXEC", "EXECUTE", "INTO",
    "OPENROWSET", "OPENQUERY", "OPENDATASOURCE", "BULK", "BACKUP", "RESTORE",
)

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_LEADING_KEYWORD_RE = re.compile(r"^\s*(WITH|SELECT)\b", re.IGNORECASE)
_OBJECT_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+"
    r"((?:\[[^\]]+\]|[A-Za-z_][\w$#]*)(?:\s*\.\s*(?:\[[^\]]+\]|[A-Za-z_][\w$#]*)){0,3})",
    re.IGNORECASE,
)


class SQLValidationError(Exception):
    """Raised when an ad-hoc SQL statement fails read-only validation."""


def _strip_noise(sql: str) -> str:
    cleaned = _BLOCK_COMMENT_RE.sub(" ", sql)
    cleaned = _LINE_COMMENT_RE.sub(" ", cleaned)
    cleaned = _STRING_LITERAL_RE.sub("''", cleaned)
    return cleaned


def _identifier_parts(identifier: str) -> list[str]:
    parts = []
    for raw in re.split(r"\s*\.\s*", identifier):
        value = raw.strip()
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
        parts.append(value)
    return parts


def validate_select_only(sql: str, allowed_schemas: Iterable[str] | None = None) -> None:
    """Validate a single read-only SELECT/CTE and optionally restrict schemas.

    Schema checking is intentionally conservative and is only defense in depth.
    One-part references are allowed because they may be CTE aliases. Three- or
    four-part object names are rejected to stop explicit cross-database/server
    references from the ad-hoc tool.
    """
    if not sql or not sql.strip():
        raise SQLValidationError("SQL statement is empty.")

    cleaned = _strip_noise(sql)
    statements = [s for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        raise SQLValidationError("Multiple SQL statements are not allowed.")
    if not _LEADING_KEYWORD_RE.match(cleaned):
        raise SQLValidationError("Only SELECT statements are allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", cleaned, re.IGNORECASE):
            raise SQLValidationError(f"Statement contains a disallowed keyword: {keyword}")

    allowed = {s.casefold() for s in (allowed_schemas or ())}
    for match in _OBJECT_REF_RE.finditer(cleaned):
        parts = _identifier_parts(match.group(1))
        if len(parts) >= 3:
            raise SQLValidationError(
                "Cross-database/server object references are not allowed in ad-hoc SQL."
            )
        if len(parts) == 2 and allowed and parts[0].casefold() not in allowed:
            raise SQLValidationError(
                f"Schema '{parts[0]}' is not allowed for ad-hoc SQL. "
                f"Allowed schemas: {', '.join(sorted(allowed))}."
            )
