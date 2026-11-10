"""Salesforce Lead fields this POC maps to, plus header auto-mapping."""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass

OBJECT_NAME = "Lead"


@dataclass(frozen=True)
class SFField:
    name: str
    label: str
    type: str = "string"  # string | email | phone | url | int | picklist
    max_length: int | None = None
    required: bool = False
    synonyms: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("synonyms")
        return d


LEAD_FIELDS: list[SFField] = [
    SFField(
        "FirstName", "First Name", max_length=40, synonyms=("first", "firstname", "givenname", "fname", "forename")
    ),
    SFField(
        "LastName",
        "Last Name",
        max_length=80,
        required=True,
        synonyms=("last", "lastname", "surname", "familyname", "lname"),
    ),
    SFField("Email", "Email", "email", 80, synonyms=("email", "emailaddress", "mail", "workemail", "businessemail")),
    SFField("Phone", "Phone", "phone", 40, synonyms=("phone", "phonenumber", "telephone", "tel", "mobile", "cell")),
    SFField(
        "Company",
        "Company",
        max_length=255,
        required=True,
        synonyms=("company", "companyname", "account", "accountname", "organization", "organisation", "employer"),
    ),
    SFField("Title", "Title", max_length=128, synonyms=("title", "jobtitle", "position", "role")),
    SFField("LeadSource", "Lead Source", "picklist", 40, synonyms=("leadsource", "source", "channel")),
    SFField("Industry", "Industry", "picklist", 40, synonyms=("industry", "vertical", "sector")),
    SFField("City", "City", max_length=40, synonyms=("city", "town")),
    SFField("State", "State/Province", max_length=80, synonyms=("state", "province", "region", "stateprovince")),
    SFField("Country", "Country", max_length=80, synonyms=("country", "nation")),
    SFField("Website", "Website", "url", 255, synonyms=("website", "url", "web", "site", "homepage", "domain")),
    SFField(
        "NumberOfEmployees",
        "Employees",
        "int",
        synonyms=("employees", "numberofemployees", "headcount", "companysize", "employeecount", "size"),
    ),
]

# Not a Salesforce field: a single "Full Name" column split into FirstName/LastName.
FULL_NAME = SFField("_FullName", "Full Name (split into First/Last)", synonyms=("name", "fullname", "contactname"))

FIELDS_BY_NAME = {f.name: f for f in [*LEAD_FIELDS, FULL_NAME]}

LEAD_SOURCES = {
    "web": "Web",
    "website": "Web",
    "webinar": "Web",
    "phone": "Phone Inquiry",
    "phone inquiry": "Phone Inquiry",
    "referral": "Partner Referral",
    "partner": "Partner Referral",
    "partner referral": "Partner Referral",
    "employee referral": "Employee Referral",
    "purchased list": "Purchased List",
    "list": "Purchased List",
    "event": "Other",
    "trade show": "Other",
    "other": "Other",
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Map each CSV header to the best Salesforce field (or None). Each field is used at most once."""
    candidates = [*LEAD_FIELDS, FULL_NAME]
    scored: list[tuple[float, str, str]] = []
    for h in headers:
        n = _norm(h)
        if not n:
            continue
        for f in candidates:
            keys = {_norm(f.name), _norm(f.label), *f.synonyms}
            if n in keys:
                score = 1.0
            else:
                score = max(difflib.SequenceMatcher(None, n, k).ratio() for k in keys)
            if score >= 0.82:
                scored.append((score, h, f.name))

    mapping: dict[str, str | None] = {h: None for h in headers}
    used: set[str] = set()
    for _score, h, field in sorted(scored, key=lambda s: -s[0]):
        if mapping[h] is None and field not in used:
            mapping[h] = field
            used.add(field)
    # A full-name column is only useful when first/last aren't mapped separately.
    if "_FullName" in used and {"FirstName", "LastName"} <= used:
        for h, f in mapping.items():
            if f == "_FullName":
                mapping[h] = None
    return mapping
