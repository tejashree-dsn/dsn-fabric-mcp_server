"""Local disk-backed result cache for bounded Claude previews, paging and export."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Iterator


class ResultStoreError(Exception):
    pass


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "dataset"


class ResultStore:
    def __init__(self, base_dir: Path, ttl_hours: int = 24) -> None:
        self.base_dir = base_dir
        self.ttl_seconds = ttl_hours * 3600
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_expired()

    def cleanup_expired(self) -> None:
        now = time.time()
        for path in self.base_dir.iterdir():
            if not path.is_dir():
                continue
            try:
                if now - path.stat().st_mtime > self.ttl_seconds:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def create_query(self, metadata: dict[str, Any]) -> str:
        self.cleanup_expired()
        query_id = uuid.uuid4().hex
        qdir = self.base_dir / query_id
        qdir.mkdir(parents=True, exist_ok=False)
        payload = dict(metadata)
        payload["query_id"] = query_id
        payload["created_at_epoch"] = time.time()
        payload["datasets"] = {}
        self._write_meta(query_id, payload)
        return query_id

    def delete_query(self, query_id: str) -> None:
        qdir = self._query_dir(query_id)
        shutil.rmtree(qdir, ignore_errors=True)

    def _query_dir(self, query_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", query_id):
            raise ResultStoreError("Invalid query_id format.")
        qdir = self.base_dir / query_id
        if not qdir.exists():
            raise ResultStoreError(
                "Result not found or expired. Re-run dsn_query to create a fresh result."
            )
        return qdir

    def _meta_path(self, query_id: str) -> Path:
        return self._query_dir(query_id) / "meta.json"

    def _write_meta(self, query_id: str, payload: dict[str, Any]) -> None:
        qdir = self.base_dir / query_id
        tmp = qdir / "meta.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(qdir / "meta.json")

    def get_metadata(self, query_id: str) -> dict[str, Any]:
        path = self._meta_path(query_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResultStoreError("Cached result metadata is unreadable.") from exc

    def update_metadata(self, query_id: str, **changes: Any) -> None:
        meta = self.get_metadata(query_id)
        meta.update(changes)
        self._write_meta(query_id, meta)

    def begin_dataset(
        self,
        query_id: str,
        name: str,
        *,
        template_name: str,
        query_hash: str,
    ) -> None:
        meta = self.get_metadata(query_id)
        filename = f"{_slug(name)}.jsonl"
        path = self._query_dir(query_id) / filename
        path.write_text("", encoding="utf-8")
        meta["datasets"][name] = {
            "name": name,
            "file": filename,
            "template_name": template_name,
            "query_hash": query_hash,
            "columns": [],
            "row_count": 0,
            "truncated": False,
        }
        self._write_meta(query_id, meta)

    def append_rows(self, query_id: str, dataset: str, rows: Iterable[list[Any]]) -> None:
        meta = self.get_metadata(query_id)
        info = meta.get("datasets", {}).get(dataset)
        if not info:
            raise ResultStoreError(f"Unknown dataset '{dataset}'.")
        path = self._query_dir(query_id) / info["file"]
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str))
                fh.write("\n")

    def finalize_dataset(
        self,
        query_id: str,
        dataset: str,
        *,
        columns: list[str],
        row_count: int,
        truncated: bool,
    ) -> None:
        meta = self.get_metadata(query_id)
        info = meta.get("datasets", {}).get(dataset)
        if not info:
            raise ResultStoreError(f"Unknown dataset '{dataset}'.")
        info["columns"] = columns
        info["row_count"] = row_count
        info["truncated"] = truncated
        self._write_meta(query_id, meta)

    def set_export(self, query_id: str, path: Path) -> None:
        meta = self.get_metadata(query_id)
        meta["export_path"] = str(path)
        meta["export_uri"] = path.resolve().as_uri()
        self._write_meta(query_id, meta)

    def iter_rows(self, query_id: str, dataset: str) -> Iterator[list[Any]]:
        meta = self.get_metadata(query_id)
        info = meta.get("datasets", {}).get(dataset)
        if not info:
            raise ResultStoreError(f"Unknown dataset '{dataset}'.")
        path = self._query_dir(query_id) / info["file"]
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def get_page(
        self,
        query_id: str,
        dataset: str,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        meta = self.get_metadata(query_id)
        info = meta.get("datasets", {}).get(dataset)
        if not info:
            raise ResultStoreError(f"Unknown dataset '{dataset}'.")

        rows: list[list[Any]] = []
        for i, row in enumerate(self.iter_rows(query_id, dataset)):
            if i < offset:
                continue
            if len(rows) >= limit:
                break
            rows.append(row)

        total = int(info.get("row_count", 0))
        returned = len(rows)
        return {
            "columns": info.get("columns", []),
            "rows": rows,
            "offset": offset,
            "returned_rows": returned,
            "total_rows": total,
            "has_more": offset + returned < total,
            "truncated": bool(info.get("truncated", False)),
        }
