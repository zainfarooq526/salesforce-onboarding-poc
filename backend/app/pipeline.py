"""Import pipeline: upload CSV -> apply mapping (normalize, validate, dedupe) -> sync to Salesforce."""

from __future__ import annotations

import csv
import io
import logging

from app.db import Database, dumps
from app.dedupe import dedupe, dedupe_key
from app.fields import suggest_mapping
from app.salesforce import SalesforceAPI
from app.transform import mapping_problems, transform_row

log = logging.getLogger(__name__)

MAX_ROWS = 10_000


class PipelineError(ValueError):
    pass


# -- 1. upload -----------------------------------------------------------------------------


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text.strip():
        raise PipelineError("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    if not headers:
        raise PipelineError("No header row found")
    rows = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() if isinstance(v, str) else "" for k, v in row.items() if k}
        if any(clean.values()):
            rows.append(clean)
        if len(rows) > MAX_ROWS:
            raise PipelineError(f"File has more than {MAX_ROWS:,} rows")
    if not rows:
        raise PipelineError("No data rows found")
    return headers, rows


def create_import(db: Database, filename: str, data: bytes) -> dict:
    headers, rows = parse_csv(data)
    job = db.fetchone(
        "INSERT INTO import_jobs (filename, headers, total_rows) VALUES (%s, %s::jsonb, %s) RETURNING *",
        (filename, dumps(headers), len(rows)),
    )
    db.executemany(
        "INSERT INTO staged_records (job_id, row_number, raw) VALUES (%s, %s, %s::jsonb)",
        [(job["id"], i + 1, dumps(r)) for i, r in enumerate(rows)],
    )
    return {**job, "preview": rows[:5], "suggested_mapping": suggest_mapping(headers)}


# -- 2. mapping, validation, dedupe ----------------------------------------------------------


def apply_mapping(db: Database, job_id: int, mapping: dict[str, str | None]) -> dict:
    job = get_job(db, job_id)
    if job["status"] in ("synced", "partial"):
        raise PipelineError("This import has already been synced")
    unknown = set(mapping) - set(job["headers"])
    if unknown:
        raise PipelineError(f"Mapping references columns not in the file: {', '.join(sorted(unknown))}")
    problems = mapping_problems(mapping)
    if problems:
        raise PipelineError("; ".join(problems))

    rows = db.fetchall(
        "SELECT id, row_number, raw FROM staged_records WHERE job_id = %s ORDER BY row_number", (job_id,)
    )
    results = [transform_row(r["raw"], mapping) for r in rows]

    valid_idx = [i for i, res in enumerate(results) if res.valid]
    merged, groups = dedupe([results[i].record for i in valid_idx])

    updates: dict[int, dict] = {}
    for i, res in enumerate(results):
        updates[i] = {
            "mapped": res.record,
            "status": "valid" if res.valid else "invalid",
            "errors": res.errors,
            "warnings": list(res.warnings),
            "dedupe_key": dedupe_key(res.record) if res.valid else None,
            "duplicate_of": None,
            "merged_from": [],
        }
    for pos, i in enumerate(valid_idx):
        updates[i]["mapped"] = merged[pos]
    for survivor_pos, group in groups.items():
        s = valid_idx[survivor_pos]
        updates[s]["merged_from"] = [rows[valid_idx[d]]["row_number"] for d in group.duplicates]
        if group.filled_fields:
            filled = ", ".join(f"{k} (row {rows[valid_idx[p]]['row_number']})" for k, p in group.filled_fields.items())
            updates[s]["warnings"].append(f"Merged from duplicate: {filled}")
        for d in group.duplicates:
            u = updates[valid_idx[d]]
            u["status"] = "duplicate"
            u["duplicate_of"] = rows[s]["row_number"]

    db.executemany(
        "UPDATE staged_records SET mapped = %s::jsonb, status = %s, errors = %s::jsonb, warnings = %s::jsonb, "
        "dedupe_key = %s, duplicate_of = %s, merged_from = %s::jsonb, sf_id = NULL, sf_action = NULL, "
        "sf_error = NULL WHERE id = %s",
        [
            (
                dumps(u["mapped"]),
                u["status"],
                dumps(u["errors"]),
                dumps(u["warnings"]),
                u["dedupe_key"],
                u["duplicate_of"],
                dumps(u["merged_from"]),
                rows[i]["id"],
            )
            for i, u in updates.items()
        ],
    )
    counts = {s: sum(1 for u in updates.values() if u["status"] == s) for s in ("valid", "invalid", "duplicate")}
    db.execute(
        "UPDATE import_jobs SET mapping = %s::jsonb, status = 'mapped', valid_rows = %s, invalid_rows = %s, "
        "duplicate_rows = %s WHERE id = %s",
        (dumps(mapping), counts["valid"], counts["invalid"], counts["duplicate"], job_id),
    )
    return get_job(db, job_id)


# -- 3. sync -----------------------------------------------------------------------------------


def sync_job(db: Database, job_id: int, sf: SalesforceAPI) -> dict:
    job = get_job(db, job_id)
    if job["status"] == "uploaded":
        raise PipelineError("Map the fields before syncing")
    rows = db.fetchall(
        "SELECT id, row_number, mapped FROM staged_records WHERE job_id = %s AND status IN ('valid', 'failed') "
        "ORDER BY row_number",
        (job_id,),
    )
    if not rows:
        raise PipelineError("Nothing to sync")

    # Match against what's already in Salesforce so re-imports update instead of duplicating.
    by_email = sf.find_leads_by_email([str(r["mapped"].get("Email") or "") for r in rows])
    no_email = [r for r in rows if not r["mapped"].get("Email")]
    by_name: dict[str, str] = {}
    if no_email:
        for lead in sf.find_leads_without_email([str(r["mapped"].get("LastName") or "") for r in no_email]):
            key = dedupe_key(lead)
            if key:
                by_name.setdefault(key, lead["Id"])

    to_create, to_update = [], []
    for r in rows:
        email = str(r["mapped"].get("Email") or "").lower()
        name_key = None if email else dedupe_key(r["mapped"])
        sf_id = by_email.get(email) if email else (by_name.get(name_key) if name_key else None)
        (to_update if sf_id else to_create).append((r, {**r["mapped"], "Id": sf_id} if sf_id else r["mapped"]))

    results = []
    if to_create:
        results += [
            (r, "created", res)
            for (r, _), res in zip(to_create, sf.create_leads([p for _, p in to_create]), strict=True)
        ]
    if to_update:
        results += [
            (r, "updated", res)
            for (r, _), res in zip(to_update, sf.update_leads([p for _, p in to_update]), strict=True)
        ]

    db.executemany(
        "UPDATE staged_records SET status = %s, sf_id = %s, sf_action = %s, sf_error = %s WHERE id = %s",
        [
            ("synced" if res.success else "failed", res.id, action if res.success else None, res.error, r["id"])
            for r, action, res in results
        ],
    )
    created = sum(1 for _, a, res in results if res.success and a == "created")
    updated = sum(1 for _, a, res in results if res.success and a == "updated")
    failed = sum(1 for _, _, res in results if not res.success)
    db.execute(
        "UPDATE import_jobs SET status = %s, created_rows = created_rows + %s, updated_rows = updated_rows + %s, "
        "failed_rows = %s, synced_at = CURRENT_TIMESTAMP WHERE id = %s",
        ("partial" if failed else "synced", created, updated, failed, job_id),
    )
    log.info("Job %s synced: %s created, %s updated, %s failed", job_id, created, updated, failed)
    return get_job(db, job_id)


# -- reads -------------------------------------------------------------------------------------


def get_job(db: Database, job_id: int) -> dict:
    job = db.fetchone("SELECT * FROM import_jobs WHERE id = %s", (job_id,))
    if job is None:
        raise LookupError(f"Import {job_id} not found")
    return job


def list_jobs(db: Database, limit: int = 50) -> list[dict]:
    return db.fetchall("SELECT * FROM import_jobs ORDER BY id DESC LIMIT %s", (limit,))


def get_records(db: Database, job_id: int, status: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    get_job(db, job_id)
    where, params = "job_id = %s", [job_id]
    if status:
        where += " AND status = %s"
        params.append(status)
    total = db.fetchone(f"SELECT COUNT(*) AS n FROM staged_records WHERE {where}", tuple(params))["n"]
    items = db.fetchall(
        f"SELECT * FROM staged_records WHERE {where} ORDER BY row_number LIMIT %s OFFSET %s",
        (*params, page_size, (page - 1) * page_size),
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def errors_csv(db: Database, job_id: int) -> str:
    rows = db.fetchall(
        "SELECT row_number, status, raw, errors, sf_error, duplicate_of FROM staged_records "
        "WHERE job_id = %s AND status IN ('invalid', 'failed', 'duplicate') ORDER BY row_number",
        (job_id,),
    )
    headers = get_job(db, job_id)["headers"]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["row_number", "status", "reason", *headers])
    for r in rows:
        if r["status"] == "duplicate":
            reason = f"Duplicate of row {r['duplicate_of']} (merged)"
        else:
            reason = "; ".join(r["errors"]) or r["sf_error"] or ""
        w.writerow([r["row_number"], r["status"], reason, *[r["raw"].get(h, "") for h in headers]])
    return out.getvalue()
