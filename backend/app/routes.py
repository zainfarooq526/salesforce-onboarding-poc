"""REST API consumed by the React frontend."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from app import __version__, pipeline
from app.fields import FULL_NAME, LEAD_FIELDS, OBJECT_NAME, suggest_mapping
from app.salesforce import SalesforceError

api = Blueprint("api", __name__, url_prefix="/api")

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "leads_sample.csv"


def _db():
    return current_app.extensions["db"]


def _sf():
    return current_app.extensions["salesforce"]


@api.errorhandler(pipeline.PipelineError)
def _bad_request(exc):
    return jsonify(error=str(exc)), 400


@api.errorhandler(LookupError)
def _not_found(exc):
    return jsonify(error=str(exc)), 404


@api.errorhandler(SalesforceError)
def _sf_error(exc):
    return jsonify(error=f"Salesforce error: {exc}"), 502


@api.get("/health")
def health():
    return {"status": "ok", "version": __version__, "database": _db().kind, "salesforce": _sf().mode}


@api.get("/salesforce/fields")
def fields():
    return {"object": OBJECT_NAME, "fields": [f.to_dict() for f in [*LEAD_FIELDS, FULL_NAME]]}


@api.post("/imports")
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise pipeline.PipelineError("Attach a CSV file as 'file'")
    if not file.filename.lower().endswith((".csv", ".txt")):
        raise pipeline.PipelineError("Only .csv files are supported")
    return pipeline.create_import(_db(), file.filename, file.read()), 201


@api.post("/imports/sample")
def upload_sample():
    return pipeline.create_import(_db(), SAMPLE_CSV.name, SAMPLE_CSV.read_bytes()), 201


@api.get("/imports")
def list_imports():
    return {"items": pipeline.list_jobs(_db())}


@api.get("/imports/<int:job_id>")
def get_import(job_id: int):
    job = pipeline.get_job(_db(), job_id)
    preview = [r["raw"] for r in pipeline.get_records(_db(), job_id, page_size=5)["items"]]
    return {**job, "preview": preview, "suggested_mapping": suggest_mapping(job["headers"])}


@api.put("/imports/<int:job_id>/mapping")
def set_mapping(job_id: int):
    body = request.get_json(silent=True) or {}
    mapping = body.get("mapping")
    if not isinstance(mapping, dict):
        raise pipeline.PipelineError('Body must be {"mapping": {"CSV column": "SalesforceField" | null}}')
    return pipeline.apply_mapping(_db(), job_id, {str(k): (v or None) for k, v in mapping.items()})


@api.get("/imports/<int:job_id>/records")
def records(job_id: int):
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(200, max(1, request.args.get("page_size", 50, type=int)))
    return pipeline.get_records(_db(), job_id, request.args.get("status") or None, page, page_size)


@api.post("/imports/<int:job_id>/sync")
def sync(job_id: int):
    return pipeline.sync_job(_db(), job_id, _sf())


@api.get("/imports/<int:job_id>/errors.csv")
def errors_csv(job_id: int):
    return Response(
        pipeline.errors_csv(_db(), job_id),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=import-{job_id}-exceptions.csv"},
    )
