import io

from eval.run_eval import run
from tests.conftest import TEST_DB

CSV = (
    "Full Name,Email,Company,Title\n"
    "Jane Doe,jane@acme.example,Acme,CTO\n"
    "John Roe,not-an-email,Acme,\n"
    "Jane Doe,JANE@acme.example,Acme,\n"
    "Maria Gonzalez,maria.gonzalez@northwind.example,Northwind,CFO\n"
)


def upload(client, text=CSV, name="leads.csv"):
    return client.post(
        "/api/imports", data={"file": (io.BytesIO(text.encode()), name)}, content_type="multipart/form-data"
    )


def test_health(client):
    assert client.get("/api/health").json["salesforce"] == "mock"


def test_fields(client):
    names = [f["name"] for f in client.get("/api/salesforce/fields").json["fields"]]
    assert "LastName" in names and "Company" in names


def test_full_flow(client, sf):
    r = upload(client)
    assert r.status_code == 201
    job = r.json
    assert job["total_rows"] == 4 and len(job["preview"]) == 4
    assert job["suggested_mapping"] == {
        "Full Name": "_FullName",
        "Email": "Email",
        "Company": "Company",
        "Title": "Title",
    }

    r = client.put(f"/api/imports/{job['id']}/mapping", json={"mapping": job["suggested_mapping"]})
    assert r.status_code == 200
    assert (r.json["valid_rows"], r.json["invalid_rows"], r.json["duplicate_rows"]) == (2, 1, 1)

    r = client.post(f"/api/imports/{job['id']}/sync")
    assert r.status_code == 200
    assert (r.json["status"], r.json["created_rows"], r.json["updated_rows"]) == ("synced", 1, 1)

    jane = next(lead for lead in sf.leads.values() if lead.get("Email") == "jane@acme.example")
    assert jane["FirstName"] == "Jane" and jane["LastName"] == "Doe"

    records = client.get(f"/api/imports/{job['id']}/records").json
    assert records["total"] == 4
    assert {r["status"] for r in records["items"]} == {"synced", "invalid", "duplicate"}
    invalid = client.get(f"/api/imports/{job['id']}/records?status=invalid").json["items"]
    assert invalid[0]["errors"] == ["Invalid email: not-an-email"]

    csv_text = client.get(f"/api/imports/{job['id']}/errors.csv").data.decode()
    assert "Invalid email" in csv_text and "Duplicate of row 1" in csv_text

    assert client.get("/api/imports").json["items"][0]["id"] == job["id"]


def test_mapping_validation_errors(client):
    job = upload(client).json
    r = client.put(f"/api/imports/{job['id']}/mapping", json={"mapping": {"Email": "Email"}})
    assert r.status_code == 400 and "Last Name" in r.json["error"]
    r = client.put(f"/api/imports/{job['id']}/mapping", json={"mapping": {"Nope": "LastName"}})
    assert r.status_code == 400


def test_sync_requires_mapping(client):
    job = upload(client).json
    assert client.post(f"/api/imports/{job['id']}/sync").status_code == 400


def test_cannot_remap_after_sync(client):
    job = upload(client).json
    client.put(f"/api/imports/{job['id']}/mapping", json={"mapping": job["suggested_mapping"]})
    client.post(f"/api/imports/{job['id']}/sync")
    r = client.put(f"/api/imports/{job['id']}/mapping", json={"mapping": job["suggested_mapping"]})
    assert r.status_code == 400


def test_upload_rejects_bad_files(client):
    assert upload(client, "", "empty.csv").status_code == 400
    assert upload(client, "a,b\n", "headers_only.csv").status_code == 400
    assert upload(client, CSV, "leads.xlsx").status_code == 400
    assert client.post("/api/imports").status_code == 400


def test_semicolon_and_latin1_csv(client):
    data = "Nom;Last Name;Company\nJosé;Pérez;Café SA\n".encode("latin-1")
    r = client.post("/api/imports", data={"file": (io.BytesIO(data), "eu.csv")}, content_type="multipart/form-data")
    assert r.status_code == 201 and r.json["preview"][0]["Last Name"] == "Pérez"


def test_sample_endpoint(client):
    r = client.post("/api/imports/sample")
    assert r.status_code == 201 and r.json["total_rows"] == 24


def test_missing_import_is_404(client):
    assert client.get("/api/imports/9999").status_code == 404


def test_evaluation_100_records_5_criteria(app):
    result = run(TEST_DB)
    assert result["records"] == 100
    assert [c["name"] for c in result["criteria"]] == [
        "Field mapping",
        "Validation",
        "Dedupe & merge",
        "Sync accuracy",
        "Idempotency",
    ]
    assert result["all_passed"], [c["failures"] for c in result["criteria"]]
