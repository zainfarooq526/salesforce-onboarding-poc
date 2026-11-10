"""Salesforce REST API client (OAuth 2.0 client credentials) and an in-memory mock.

Both expose the same three calls the pipeline needs:
    find_leads_by_email(emails) -> {email: Id}
    create_leads(records)       -> [SaveResult]
    update_leads(records)       -> [SaveResult]   (each record carries "Id")
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from typing import Protocol

import requests

log = logging.getLogger(__name__)

BATCH_SIZE = 200  # sObject Collections limit per request
SOQL_IN_BATCH = 100


@dataclass
class SaveResult:
    success: bool
    id: str | None = None
    error: str | None = None


class SalesforceAPI(Protocol):
    mode: str

    def find_leads_by_email(self, emails: list[str]) -> dict[str, str]: ...
    def find_leads_without_email(self, last_names: list[str]) -> list[dict]: ...
    def create_leads(self, records: list[dict]) -> list[SaveResult]: ...
    def update_leads(self, records: list[dict]) -> list[SaveResult]: ...


class SalesforceError(RuntimeError):
    pass


def soql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _parse_results(payload: list[dict]) -> list[SaveResult]:
    out = []
    for r in payload:
        if r.get("success"):
            out.append(SaveResult(True, r.get("id")))
        else:
            msg = "; ".join(f"{e.get('statusCode')}: {e.get('message')}" for e in r.get("errors", []))
            out.append(SaveResult(False, r.get("id"), msg or "Unknown error"))
    return out


class SalesforceClient:
    mode = "live"

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        api_version: str = "61.0",
        session: requests.Session | None = None,
        timeout: float = 30,
    ):
        self.instance_url = instance_url.rstrip("/")
        self.base = f"{self.instance_url}/services/data/v{api_version}"
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
        self.timeout = timeout

    @classmethod
    def from_client_credentials(
        cls,
        domain_url: str,
        client_id: str,
        client_secret: str,
        api_version: str = "61.0",
        session: requests.Session | None = None,
    ):
        """Authenticate with a Connected App's client-credentials flow (needs a 'Run As' user)."""
        session = session or requests.Session()
        resp = session.post(
            f"{domain_url.rstrip('/')}/services/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=30,
        )
        if resp.status_code != 200:
            raise SalesforceError(f"OAuth failed ({resp.status_code}): {resp.text[:300]}")
        token = resp.json()
        return cls(token["instance_url"], token["access_token"], api_version, session)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            raise SalesforceError(f"{method} {url} -> {resp.status_code}: {resp.text[:500]}")
        return resp

    def query(self, soql: str) -> list[dict]:
        records: list[dict] = []
        data = self._request("GET", f"{self.base}/query", params={"q": soql}).json()
        records += data.get("records", [])
        while not data.get("done", True) and data.get("nextRecordsUrl"):
            data = self._request("GET", self.instance_url + data["nextRecordsUrl"]).json()
            records += data.get("records", [])
        return records

    def find_leads_by_email(self, emails: list[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for chunk in _chunks(sorted({e.lower() for e in emails if e}), SOQL_IN_BATCH):
            soql = (
                "SELECT Id, Email FROM Lead WHERE IsConverted = false AND Email IN ("
                + ",".join(soql_quote(e) for e in chunk)
                + ") ORDER BY CreatedDate ASC"
            )
            for r in self.query(soql):
                found.setdefault(r["Email"].lower(), r["Id"])
        return found

    def find_leads_without_email(self, last_names: list[str]) -> list[dict]:
        """Candidates for name+company matching when a record has no email."""
        found: list[dict] = []
        for chunk in _chunks(sorted({n for n in last_names if n}), SOQL_IN_BATCH):
            soql = (
                "SELECT Id, FirstName, LastName, Company FROM Lead WHERE IsConverted = false AND Email = null "
                "AND LastName IN (" + ",".join(soql_quote(n) for n in chunk) + ")"
            )
            found += self.query(soql)
        return found

    def _collection(self, method: str, records: list[dict]) -> list[SaveResult]:
        results: list[SaveResult] = []
        for chunk in _chunks(records, BATCH_SIZE):
            body = {"allOrNone": False, "records": [{"attributes": {"type": "Lead"}, **r} for r in chunk]}
            results += _parse_results(self._request(method, f"{self.base}/composite/sobjects", json=body).json())
        return results

    def create_leads(self, records: list[dict]) -> list[SaveResult]:
        return self._collection("POST", records)

    def update_leads(self, records: list[dict]) -> list[SaveResult]:
        return self._collection("PATCH", records)


class MockSalesforce:
    """In-memory stand-in so the POC runs without a Salesforce org. Mirrors the real API's
    behaviour that matters here: required fields, 200-record batches, per-record results."""

    mode = "mock"

    SEED = [
        {
            "FirstName": "Maria",
            "LastName": "Gonzalez",
            "Email": "maria.gonzalez@northwind.example",
            "Company": "Northwind",
        },
        {"FirstName": "Tom", "LastName": "Becker", "Email": "tom.becker@contoso.example", "Company": "Contoso"},
    ]

    def __init__(self, seed: list[dict] | None = None):
        self.leads: dict[str, dict] = {}
        self.api_calls = 0
        for r in self.SEED if seed is None else seed:
            self._insert(dict(r))

    @staticmethod
    def _new_id() -> str:
        return "00Q" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(15))

    def _insert(self, rec: dict) -> str:
        lead_id = self._new_id()
        self.leads[lead_id] = {**rec, "Id": lead_id}
        return lead_id

    def find_leads_by_email(self, emails: list[str]) -> dict[str, str]:
        wanted = {e.lower() for e in emails if e}
        self.api_calls += max(1, -(-len(wanted) // SOQL_IN_BATCH))
        found: dict[str, str] = {}
        for lead in self.leads.values():
            email = str(lead.get("Email") or "").lower()
            if email in wanted:
                found.setdefault(email, lead["Id"])
        return found

    def find_leads_without_email(self, last_names: list[str]) -> list[dict]:
        wanted = {n for n in last_names if n}
        self.api_calls += max(1, -(-len(wanted) // SOQL_IN_BATCH))
        return [dict(lead) for lead in self.leads.values() if not lead.get("Email") and lead.get("LastName") in wanted]

    def create_leads(self, records: list[dict]) -> list[SaveResult]:
        self.api_calls += max(1, -(-len(records) // BATCH_SIZE))
        out = []
        for r in records:
            missing = [f for f in ("LastName", "Company") if not r.get(f)]
            if missing:
                out.append(SaveResult(False, error=f"REQUIRED_FIELD_MISSING: {', '.join(missing)}"))
            else:
                out.append(SaveResult(True, self._insert(dict(r))))
        return out

    def update_leads(self, records: list[dict]) -> list[SaveResult]:
        self.api_calls += max(1, -(-len(records) // BATCH_SIZE))
        out = []
        for r in records:
            lead = self.leads.get(r.get("Id", ""))
            if lead is None:
                out.append(SaveResult(False, r.get("Id"), "ENTITY_IS_DELETED: entity is deleted"))
            else:
                lead.update(r)
                out.append(SaveResult(True, lead["Id"]))
        return out
