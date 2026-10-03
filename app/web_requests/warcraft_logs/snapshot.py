"""Credential-free recording of WCL report metadata and ordered event pages."""
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from .errors import SnapshotError


@dataclass(frozen=True)
class WCLSnapshot:
    report: dict[str, Any]
    event_pages: dict[int, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "provider": "warcraftlogs", "report": self.report,
                "event_pages": {str(key): value for key, value in self.event_pages.items()}}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "WCLSnapshot":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotError("could not read WCL snapshot JSON") from exc
        if not isinstance(data, dict):
            raise SnapshotError("WCL snapshot must be an object")
        if data.get("schema_version") != 1 or data.get("provider") != "warcraftlogs":
            raise SnapshotError("unsupported WCL snapshot schema or provider")
        report, pages = data.get("report"), data.get("event_pages")
        if not isinstance(report, dict):
            raise SnapshotError("WCL snapshot report must be an object")
        if not isinstance(pages, dict) or any(not isinstance(v, list) for v in pages.values()):
            raise SnapshotError("WCL snapshot event_pages must map fight IDs to page lists")
        for page_list in pages.values():
            if any(not isinstance(page, dict) or not isinstance(page.get("data"), list)
                   for page in page_list):
                raise SnapshotError("each WCL event page must contain a data list")
        try:
            return cls(report, {int(k): v for k, v in pages.items()})
        except (TypeError, ValueError) as exc:
            raise SnapshotError("WCL snapshot contains an invalid fight ID") from exc
