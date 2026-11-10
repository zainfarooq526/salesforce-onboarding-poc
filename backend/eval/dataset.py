"""Deterministic 100-record test dataset with ground truth for the evaluation.

Composition (100 rows):
  80 unique people  - messy but valid formatting (case, phone formats, websites, "1,200")
                      12 of them already exist in Salesforce  -> expected "updated"
                       4 of them have no email                 -> matched by name + company
  10 duplicate rows - same person again (email case/whitespace changed); 5 of them carry a
                      Title the first row is missing, which the merge must keep
  10 invalid rows   - 4 bad emails, 3 missing last name, 3 missing company
"""

from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass, field

HEADERS = [
    "Given Name",
    "Surname",
    "Work Email",
    "Mobile",
    "Organization",
    "Position",
    "Source",
    "Town",
    "Province",
    "Nation",
    "Headcount",
    "Homepage",
]

EXPECTED_MAPPING = {
    "Given Name": "FirstName",
    "Surname": "LastName",
    "Work Email": "Email",
    "Mobile": "Phone",
    "Organization": "Company",
    "Position": "Title",
    "Source": "LeadSource",
    "Town": "City",
    "Province": "State",
    "Nation": "Country",
    "Headcount": "NumberOfEmployees",
    "Homepage": "Website",
}

FIRST = [
    "Ava",
    "Liam",
    "Noah",
    "Emma",
    "Mia",
    "Lucas",
    "Zara",
    "Omar",
    "Ines",
    "Kai",
    "Nora",
    "Leo",
    "Ivy",
    "Arjun",
    "Sana",
    "Yuki",
    "Mateo",
    "Elena",
    "Hugo",
    "Lena",
    "Amir",
    "Chloe",
    "Felix",
    "Rosa",
    "Theo",
]
LAST = [
    "Walker",
    "Nguyen",
    "Garcia",
    "Hughes",
    "Moreau",
    "Kowalski",
    "Haddad",
    "Silva",
    "Tanaka",
    "Okoye",
    "Fischer",
    "Larsen",
    "Reyes",
    "Bianchi",
    "Novak",
    "Ahmed",
    "Costa",
    "Park",
    "Jensen",
    "Romero",
]
COMPANIES = [
    "Acme Robotics",
    "Bluefin Analytics",
    "Cedar Health",
    "Delta Freight",
    "Evergreen Bank",
    "Foxglove Media",
    "Granite Insurance",
    "Helios Solar",
    "Ironwood Labs",
    "Juniper Retail",
    "Keystone Legal",
    "Lumen Education",
    "Mosaic Travel",
    "Nimbus Cloud",
    "Orchid Foods",
]
TITLES = ["VP Sales", "Operations Manager", "CTO", "Head of Data", "Procurement Lead", "CFO", "IT Director"]
CITIES = [("Austin", "TX"), ("Denver", "CO"), ("Seattle", "WA"), ("Boston", "MA"), ("Chicago", "IL"), ("Miami", "FL")]
SOURCES = [
    ("web", "Web"),
    ("Website", "Web"),
    ("referral", "Partner Referral"),
    ("Partner", "Partner Referral"),
    ("phone", "Phone Inquiry"),
    ("Purchased List", "Purchased List"),
]


@dataclass
class Case:
    row_number: int
    raw: dict[str, str]
    kind: str  # unique | duplicate | invalid
    person: int | None = None  # index of the unique person this row belongs to
    expected: dict = field(default_factory=dict)  # canonical Salesforce values (unique rows)
    exists_in_sf: bool = False
    invalid_reason: str | None = None  # "email" | "last_name" | "company"
    fills_title: bool = False


@dataclass
class Dataset:
    cases: list[Case]
    existing_sf: list[dict]  # leads to seed the (mock) org with before the run

    def to_csv(self) -> bytes:
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=HEADERS)
        w.writeheader()
        for c in self.cases:
            w.writerow(c.raw)
        return out.getvalue().encode()


def _messy_case(rng: random.Random, s: str) -> str:
    return rng.choice([s, s.upper(), s.lower()])


def _messy_phone(rng: random.Random, digits: str) -> str:
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return rng.choice([f"({a}) {b}-{c}", f"{a}.{b}.{c}", f"{a} {b} {c}", f"+1 {a}-{b}-{c}", f"{a}{b}{c}"])


def build(seed: int = 42) -> Dataset:
    rng = random.Random(seed)
    people: list[dict] = []
    used_names = set()
    while len(people) < 80:
        first, last, company = rng.choice(FIRST), rng.choice(LAST), rng.choice(COMPANIES)
        if (first, last, company) in used_names:
            continue
        used_names.add((first, last, company))
        domain = company.lower().replace(" ", "") + ".example"
        city, state = rng.choice(CITIES)
        src_raw, src = rng.choice(SOURCES)
        employees = rng.choice([12, 85, 240, 1200, 4800, 15000])
        phone = f"{rng.randint(201, 989)}555{rng.randint(1000, 9999)}"
        people.append(
            {
                "canonical": {
                    "FirstName": first,
                    "LastName": last,
                    "Email": f"{first}.{last}@{domain}".lower(),
                    "Phone": "+1" + phone,
                    "Company": company,
                    "Title": rng.choice(TITLES),
                    "LeadSource": src,
                    "City": city,
                    "State": state,
                    "Country": "USA",
                    "NumberOfEmployees": employees,
                    "Website": f"https://{domain}",
                },
                "raw": {
                    "Given Name": _messy_case(rng, first),
                    "Surname": _messy_case(rng, last),
                    "Work Email": rng.choice(
                        [
                            f"{first}.{last}@{domain}",
                            f"{first}.{last}@{domain}".lower(),
                            f" {first}.{last}@{domain} ".upper(),
                        ]
                    ),
                    "Mobile": _messy_phone(rng, phone),
                    "Organization": company,
                    "Position": "",
                    "Source": src_raw,
                    "Town": _messy_case(rng, city),
                    "Province": state,
                    "Nation": "USA",
                    "Headcount": rng.choice([f"{employees:,}", str(employees)]),
                    "Homepage": rng.choice([domain, f"https://{domain}", domain.upper()]),
                },
            }
        )
    for p in people:
        p["raw"]["Position"] = p["canonical"]["Title"]

    # 4 people without email (matched by name + company), 12 that already exist in Salesforce.
    no_email = set(range(70, 74))
    for i in no_email:
        people[i]["raw"]["Work Email"] = ""
        people[i]["canonical"].pop("Email")
    existing = set(range(0, 12))
    # 5 people whose first row lacks a Title that their duplicate row supplies.
    title_from_dup = set(range(20, 25))
    for i in title_from_dup:
        people[i]["raw"]["Position"] = ""

    cases: list[Case] = []
    for i, p in enumerate(people):
        canonical = dict(p["canonical"])
        cases.append(Case(0, dict(p["raw"]), "unique", i, canonical, exists_in_sf=i in existing))

    dup_people = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34]
    for i in dup_people:
        raw = dict(people[i]["raw"])
        raw["Work Email"] = "  " + people[i]["canonical"]["Email"].upper() + " "
        raw["Position"] = people[i]["canonical"]["Title"] if i in title_from_dup else ""
        raw["Mobile"] = ""
        cases.append(Case(0, raw, "duplicate", i, fills_title=i in title_from_dup))

    invalid_specs = [
        ("email", "jo.bloggs@nodomain"),
        ("email", "two@@ats.example"),
        ("email", "no-at-sign.example"),
        ("email", "spaces in@email.example"),
        ("last_name", None),
        ("last_name", None),
        ("last_name", None),
        ("company", None),
        ("company", None),
        ("company", None),
    ]
    for n, (reason, bad) in enumerate(invalid_specs):
        raw = {h: "" for h in HEADERS}
        raw.update(
            {
                "Given Name": "Test",
                "Surname": f"Invalid{n}",
                "Organization": "Zeta Corp",
                "Work Email": f"invalid{n}@zetacorp.example",
            }
        )
        if reason == "email":
            raw["Work Email"] = bad
        elif reason == "last_name":
            raw["Surname"] = ""
        else:
            raw["Organization"] = ""
        cases.append(Case(0, raw, "invalid", invalid_reason=reason))

    rng.shuffle(cases)
    # Duplicates must come after the row they duplicate so the first occurrence survives.
    first_seen: dict[int, int] = {}
    ordered: list[Case] = []
    deferred: list[Case] = []
    for c in cases:
        if c.kind == "duplicate" and c.person not in first_seen:
            deferred.append(c)
            continue
        ordered.append(c)
        if c.kind == "unique":
            first_seen[c.person] = len(ordered)
            ordered += [d for d in deferred if d.person == c.person]
            deferred = [d for d in deferred if d.person != c.person]
    for n, c in enumerate(ordered, start=1):
        c.row_number = n

    existing_sf = [
        {**{k: people[i]["canonical"][k] for k in ("FirstName", "LastName", "Email", "Company")}, "Title": "Old title"}
        for i in existing
    ]
    return Dataset(ordered, existing_sf)
