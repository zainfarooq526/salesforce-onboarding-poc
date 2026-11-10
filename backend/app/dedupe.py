"""In-file duplicate detection with field-level merge (survivorship)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def dedupe_key(record: dict) -> str | None:
    """Email is the primary match key; fall back to first+last+company when there's no email."""
    email = str(record.get("Email") or "").strip().lower()
    if email:
        return f"email:{email}"
    parts = [str(record.get(k) or "") for k in ("FirstName", "LastName", "Company")]
    norm = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in parts]
    if norm[1] and norm[2]:
        return "name:" + "|".join(norm)
    return None


@dataclass
class DedupeGroup:
    survivor: int  # index into the input list
    duplicates: list[int] = field(default_factory=list)
    filled_fields: dict[str, int] = field(default_factory=dict)  # field -> index it came from


def dedupe(records: list[dict]) -> tuple[list[dict], dict[int, DedupeGroup]]:
    """Group records by key. The first occurrence survives; blank fields on the survivor are
    filled from later duplicates. Returns (merged records, {survivor index: group})."""
    merged = [dict(r) for r in records]
    groups: dict[str, DedupeGroup] = {}
    for i, rec in enumerate(records):
        key = dedupe_key(rec)
        if key is None:
            continue
        if key not in groups:
            groups[key] = DedupeGroup(survivor=i)
            continue
        g = groups[key]
        g.duplicates.append(i)
        target = merged[g.survivor]
        for k, v in rec.items():
            if v not in (None, "") and target.get(k) in (None, ""):
                target[k] = v
                g.filled_fields[k] = i
    return merged, {g.survivor: g for g in groups.values() if g.duplicates}
