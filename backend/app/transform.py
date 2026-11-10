"""Apply a column mapping to a raw CSV row, then normalize and validate it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.fields import FIELDS_BY_NAME, LEAD_FIELDS, LEAD_SOURCES

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass
class TransformResult:
    record: dict[str, object]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fix_case(name: str) -> str:
    """'JANE' / 'jane' -> 'Jane'. Mixed case such as 'McDonald' is left alone."""
    if name.isupper() or name.islower():
        return "".join(p[:1].upper() + p[1:].lower() for p in re.split(r"( |-|')", name))
    return name


def split_full_name(full: str) -> tuple[str, str]:
    full = clean(full)
    if "," in full:  # "Doe, Jane"
        last, first = [p.strip() for p in full.split(",", 1)]
        return first, last
    parts = full.split(" ")
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def transform_row(raw: dict[str, str], mapping: dict[str, str | None]) -> TransformResult:
    record: dict[str, object] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for header, target in mapping.items():
        if not target:
            continue
        value = clean(raw.get(header, ""))
        if not value:
            continue
        if target == "_FullName":
            first, last = split_full_name(value)
            if first:
                record.setdefault("FirstName", first)
            if last:
                record.setdefault("LastName", last)
        else:
            record[target] = value

    for name in ("FirstName", "LastName", "City"):
        if name in record:
            record[name] = fix_case(str(record[name]))

    if "Email" in record:
        email = str(record["Email"]).lower().strip("<>").replace("mailto:", "")
        if EMAIL_RE.match(email):
            record["Email"] = email
        else:
            errors.append(f"Invalid email: {record['Email']}")

    if "Phone" in record:
        phone = normalize_phone(str(record["Phone"]))
        if phone:
            record["Phone"] = phone
        else:
            warnings.append(f"Phone kept as entered (could not normalize): {record['Phone']}")

    if "Website" in record:
        site = str(record["Website"]).lower()
        record["Website"] = site if site.startswith(("http://", "https://")) else f"https://{site}"

    if "NumberOfEmployees" in record:
        n = re.sub(r"[,\s]", "", str(record["NumberOfEmployees"]))
        if n.isdigit():
            record["NumberOfEmployees"] = int(n)
        else:
            warnings.append(f"Employees is not a number, dropped: {record.pop('NumberOfEmployees')}")

    if "LeadSource" in record:
        src = LEAD_SOURCES.get(str(record["LeadSource"]).lower())
        if src:
            record["LeadSource"] = src
        else:
            warnings.append(f"Unknown lead source '{record['LeadSource']}', set to Other")
            record["LeadSource"] = "Other"

    for f in LEAD_FIELDS:
        v = record.get(f.name)
        if isinstance(v, str) and f.max_length and len(v) > f.max_length:
            record[f.name] = v[: f.max_length]
            warnings.append(f"{f.label} truncated to {f.max_length} characters")
        if f.required and not record.get(f.name):
            errors.append(f"Missing required field: {f.label}")

    return TransformResult(record, errors, warnings)


def mapping_problems(mapping: dict[str, str | None]) -> list[str]:
    """Problems with the mapping itself (before looking at any rows)."""
    targets = [t for t in mapping.values() if t]
    problems = [f"Unknown Salesforce field: {t}" for t in targets if t not in FIELDS_BY_NAME]
    dupes = sorted({t for t in targets if targets.count(t) > 1})
    problems += [f"{FIELDS_BY_NAME[t].label} is mapped from more than one column" for t in dupes if t in FIELDS_BY_NAME]
    has_last = "LastName" in targets or "_FullName" in targets
    if not has_last:
        problems.append("Map a column to Last Name (or Full Name)")
    if "Company" not in targets:
        problems.append("Map a column to Company")
    return problems
