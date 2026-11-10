"""Run the 100-record evaluation against the full pipeline and score it on 5 criteria.

    python -m eval.run_eval                       # SQLite, mock Salesforce
    DATABASE_URL=postgresql://... python -m eval.run_eval
    python -m eval.run_eval --report ../docs/eval-report.md

Criteria:
  1. Field mapping   - auto-suggested mapping matches the expected mapping for every column
  2. Validation      - exactly the bad rows are rejected, each for the right reason
  3. Dedupe & merge  - every duplicate is caught, points at the right row, and fills missing fields
  4. Sync accuracy   - every good record lands in Salesforce with the right values and the right
                       action (create vs update existing)
  5. Idempotency     - importing and syncing the same file again creates zero new records
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline  # noqa: E402
from app.db import Database  # noqa: E402
from app.salesforce import MockSalesforce  # noqa: E402
from eval.dataset import EXPECTED_MAPPING, build  # noqa: E402

REASON_TEXT = {
    "email": "Invalid email",
    "last_name": "Missing required field: Last Name",
    "company": "Missing required field: Company",
}


@dataclass
class Criterion:
    name: str
    passed: int
    total: int
    detail: str
    failures: list[str]

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def run(database_url: str = "sqlite:///:memory:") -> dict:
    ds = build()
    db = Database(database_url)
    db.init_schema()
    sf = MockSalesforce(seed=ds.existing_sf)
    leads_before = len(sf.leads)
    data = ds.to_csv()

    t0 = time.perf_counter()
    job = pipeline.create_import(db, "eval_100.csv", data)
    suggested = job["suggested_mapping"]
    pipeline.apply_mapping(db, job["id"], suggested)
    synced = pipeline.sync_job(db, job["id"], sf)
    first_run_s = time.perf_counter() - t0
    records = {r["row_number"]: r for r in pipeline.get_records(db, job["id"], page_size=1000)["items"]}
    criteria: list[Criterion] = []

    # 1. Field mapping ------------------------------------------------------------------
    fails = [f"{h}: got {suggested.get(h)}, expected {f}" for h, f in EXPECTED_MAPPING.items() if suggested.get(h) != f]
    criteria.append(
        Criterion(
            "Field mapping",
            len(EXPECTED_MAPPING) - len(fails),
            len(EXPECTED_MAPPING),
            "Auto-suggested mapping matches expected for each CSV column",
            fails,
        )
    )

    # 2. Validation -----------------------------------------------------------------------
    fails = []
    for c in ds.cases:
        r = records[c.row_number]
        if c.kind == "invalid":
            if r["status"] != "invalid":
                fails.append(f"row {c.row_number}: bad row accepted ({c.invalid_reason})")
            elif not any(e.startswith(REASON_TEXT[c.invalid_reason]) for e in r["errors"]):
                fails.append(f"row {c.row_number}: wrong reason {r['errors']}")
        elif r["status"] == "invalid":
            fails.append(f"row {c.row_number}: good row rejected {r['errors']}")
    criteria.append(
        Criterion(
            "Validation",
            len(ds.cases) - len(fails),
            len(ds.cases),
            "Every row correctly accepted or rejected (with the right reason)",
            fails,
        )
    )

    # 3. Dedupe & merge -------------------------------------------------------------------
    first_row = {c.person: c.row_number for c in ds.cases if c.kind == "unique"}
    dup_cases = [c for c in ds.cases if c.kind == "duplicate"]
    fails = []
    for c in dup_cases:
        r = records[c.row_number]
        if r["status"] != "duplicate" or r["duplicate_of"] != first_row[c.person]:
            fails.append(f"row {c.row_number}: status={r['status']} duplicate_of={r['duplicate_of']}")
        elif c.fills_title and records[first_row[c.person]]["mapped"].get("Title") is None:
            fails.append(f"row {c.row_number}: Title not merged into row {first_row[c.person]}")
    false_dupes = [
        c.row_number for c in ds.cases if c.kind != "duplicate" and records[c.row_number]["status"] == "duplicate"
    ]
    fails += [f"row {n}: wrongly flagged as duplicate" for n in false_dupes]
    total = len(dup_cases) + len([c for c in ds.cases if c.kind != "duplicate"])
    criteria.append(
        Criterion(
            "Dedupe & merge", total - len(fails), total, "Duplicates caught and merged; no false positives", fails
        )
    )

    # 4. Sync accuracy --------------------------------------------------------------------
    fails = []
    uniques = [c for c in ds.cases if c.kind == "unique"]
    for c in uniques:
        r = records[c.row_number]
        lead = sf.leads.get(r["sf_id"] or "")
        if r["status"] != "synced" or lead is None:
            fails.append(f"row {c.row_number}: not synced ({r['status']}, {r['sf_error']})")
            continue
        want_action = "updated" if c.exists_in_sf else "created"
        if r["sf_action"] != want_action:
            fails.append(f"row {c.row_number}: {r['sf_action']}, expected {want_action}")
        wrong = {k: (lead.get(k), v) for k, v in c.expected.items() if lead.get(k) != v}
        if wrong:
            fails.append(f"row {c.row_number}: field mismatch {wrong}")
    expected_creates = sum(not c.exists_in_sf for c in uniques)
    count_ok = len(sf.leads) == leads_before + expected_creates
    if not count_ok:
        fails.append(f"org has {len(sf.leads)} leads, expected {leads_before + expected_creates}")
    criteria.append(
        Criterion(
            "Sync accuracy",
            len(uniques) + 1 - len(fails),
            len(uniques) + 1,
            "Records in Salesforce with correct values and create/update action",
            fails,
        )
    )

    # 5. Idempotency ------------------------------------------------------------------------
    t1 = time.perf_counter()
    job2 = pipeline.create_import(db, "eval_100_rerun.csv", data)
    pipeline.apply_mapping(db, job2["id"], job2["suggested_mapping"])
    rerun = pipeline.sync_job(db, job2["id"], sf)
    rerun_s = time.perf_counter() - t1
    fails = []
    if rerun["created_rows"] != 0:
        fails.append(f"re-run created {rerun['created_rows']} new records")
    if len(sf.leads) != leads_before + expected_creates:
        fails.append("lead count changed on re-run")
    if rerun["updated_rows"] != len(uniques):
        fails.append(f"re-run updated {rerun['updated_rows']}, expected {len(uniques)}")
    criteria.append(
        Criterion(
            "Idempotency",
            3 - len(fails),
            3,
            "Re-importing the same file updates records instead of duplicating them",
            fails,
        )
    )

    summary = {
        "records": len(ds.cases),
        "database": db.kind,
        "first_run": {
            k: synced[k]
            for k in ("valid_rows", "invalid_rows", "duplicate_rows", "created_rows", "updated_rows", "failed_rows")
        },
        "first_run_seconds": round(first_run_s, 3),
        "rerun_seconds": round(rerun_s, 3),
        "salesforce_api_calls": sf.api_calls,
        "criteria": [{**asdict(c), "ok": c.ok} for c in criteria],
        "all_passed": all(c.ok for c in criteria),
    }
    return summary


def to_markdown(s: dict) -> str:
    lines = [
        "# Evaluation report: 100 records, 5 criteria",
        "",
        f"Generated by `python -m eval.run_eval` against the full pipeline ({s['database']} database, "
        "mock Salesforce org seeded with 12 existing leads).",
        "",
        "| # | Criterion | Result | Score | What is checked |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(s["criteria"], 1):
        mark = "✅ Pass" if c["ok"] else "❌ Fail"
        lines.append(f"| {i} | {c['name']} | {mark} | {c['passed']}/{c['total']} | {c['detail']} |")
    fr = s["first_run"]
    lines += [
        "",
        "## Dataset",
        "",
        "- 80 unique people with messy formatting (upper/lower case, 5 phone formats, bare domains, `1,200`)",
        "- 12 of them already exist in Salesforce, 4 have no email (matched on name + company)",
        "- 10 duplicate rows (email case and spacing changed), 5 of which supply a Title the first row lacks",
        "- 10 invalid rows: 4 bad emails, 3 missing last name, 3 missing company",
        "",
        "## First run",
        "",
        f"- Valid: {fr['valid_rows']} · Invalid: {fr['invalid_rows']} · Duplicates: {fr['duplicate_rows']}",
        f"- Created: {fr['created_rows']} · Updated: {fr['updated_rows']} · Failed: {fr['failed_rows']}",
        f"- Time: {s['first_run_seconds']} s · Re-run: {s['rerun_seconds']} s · "
        f"Salesforce API calls: {s['salesforce_api_calls']}",
        "",
        f"**Overall: {'all 5 criteria passed' if s['all_passed'] else 'FAILED'}**",
    ]
    for c in s["criteria"]:
        if c["failures"]:
            lines += ["", f"### Failures: {c['name']}", "", *[f"- {f}" for f in c["failures"]]]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--report", help="write a markdown report to this path")
    p.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = p.parse_args()
    url = os.getenv("EVAL_DATABASE_URL") or os.getenv("DATABASE_URL") or "sqlite:///:memory:"
    s = run(url)
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        for i, c in enumerate(s["criteria"], 1):
            print(f"{i}. {c['name']:<16} {'PASS' if c['ok'] else 'FAIL'}  {c['passed']}/{c['total']}")
            for f in c["failures"][:5]:
                print(f"     - {f}")
        print(f"\nAll passed: {s['all_passed']}  ({s['first_run_seconds']}s, {s['salesforce_api_calls']} API calls)")
    if args.report:
        Path(args.report).write_text(to_markdown(s), encoding="utf-8")
    sys.exit(0 if s["all_passed"] else 1)


if __name__ == "__main__":
    main()
