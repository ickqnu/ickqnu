"""Append-only JSONL trade journal + per-day stats."""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(os.environ.get("TRADER_JOURNAL", str(Path.home() / ".trader" / "journal.jsonl")))
DAILY_APPROVAL_LIMIT = 5


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append(record: dict[str, Any], path: Path = DEFAULT_PATH) -> dict[str, Any]:
    record = dict(record)
    record.setdefault("id", uuid.uuid4().hex[:12])
    record.setdefault("ts", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def iter_records(path: Path = DEFAULT_PATH) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return iter(())
    def gen() -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    return gen()


def today_iso() -> str:
    return dt.date.today().isoformat()


def count_today(path: Path = DEFAULT_PATH, *, kind: str = "trade_approved") -> int:
    prefix = today_iso()
    return sum(1 for r in iter_records(path) if r.get("kind") == kind and (r.get("ts") or "").startswith(prefix))


def tripwire_active(path: Path = DEFAULT_PATH) -> tuple[bool, str | None]:
    """Tripwire = a journal record with kind='tripwire' in the last 24h that isn't overridden."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=24)
    latest_trip: dict[str, Any] | None = None
    overridden_after_trip = False
    for r in iter_records(path):
        ts = r.get("ts")
        if not ts:
            continue
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < cutoff:
            continue
        if r.get("kind") == "tripwire":
            latest_trip = r
            overridden_after_trip = False
        elif r.get("kind") == "tripwire_override" and latest_trip:
            overridden_after_trip = True
    if latest_trip and not overridden_after_trip:
        return True, latest_trip.get("reason")
    return False, None


class JournalWriter:
    """Callable used by cli_present.prompt_approval to log approved trades."""

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path

    def __call__(
        self,
        *,
        mint: str,
        symbol: str,
        size_usd: float,
        thesis: str,
        primary_pool: str | None,
        price_usd: float | None,
    ) -> dict[str, Any]:
        return append(
            {
                "kind": "trade_approved",
                "mint": mint,
                "symbol": symbol,
                "size_usd": round(size_usd, 2),
                "thesis": thesis,
                "primary_pool": primary_pool,
                "entry_price_usd": price_usd,
            },
            path=self.path,
        )


def write_tripwire(reason: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    return append({"kind": "tripwire", "reason": reason}, path=path)


def write_tripwire_override(reason: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    return append({"kind": "tripwire_override", "reason": reason}, path=path)


def summary(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    records = list(iter_records(path))
    approved = [r for r in records if r.get("kind") == "trade_approved"]
    today = today_iso()
    approved_today = [r for r in approved if (r.get("ts") or "").startswith(today)]
    tripwires = [r for r in records if r.get("kind") == "tripwire"]
    return {
        "total_records": len(records),
        "approved_total": len(approved),
        "approved_today": len(approved_today),
        "tripwires_total": len(tripwires),
        "tripwire_active": tripwire_active(path)[0],
        "path": str(path),
    }
