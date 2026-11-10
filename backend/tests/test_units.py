import pytest
import requests

from app.dedupe import dedupe, dedupe_key
from app.fields import suggest_mapping
from app.salesforce import SalesforceClient, soql_quote
from app.transform import mapping_problems, normalize_phone, split_full_name, transform_row

# -- mapping ---------------------------------------------------------------------------------


def test_suggest_mapping_handles_messy_headers():
    m = suggest_mapping(["E-mail Address", "Company Name", "Surname", "Given Name", "Phone #", "Notes"])
    assert m == {
        "E-mail Address": "Email",
        "Company Name": "Company",
        "Surname": "LastName",
        "Given Name": "FirstName",
        "Phone #": "Phone",
        "Notes": None,
    }


def test_suggest_mapping_uses_full_name_only_without_first_last():
    assert suggest_mapping(["Name", "Company"])["Name"] == "_FullName"


def test_mapping_problems_requires_last_name_and_company():
    assert len(mapping_problems({"Email": "Email"})) == 2
    assert mapping_problems({"A": "LastName", "B": "Company"}) == []
    assert any("more than one" in p for p in mapping_problems({"A": "LastName", "B": "LastName", "C": "Company"}))


# -- transform -------------------------------------------------------------------------------

MAP = {
    "first": "FirstName",
    "last": "LastName",
    "email": "Email",
    "phone": "Phone",
    "co": "Company",
    "site": "Website",
    "emp": "NumberOfEmployees",
    "src": "LeadSource",
}


def test_transform_normalizes_fields():
    res = transform_row(
        {
            "first": "JANE",
            "last": "o'neill",
            "email": " Jane@Acme.COM ",
            "phone": "(415) 555-0132",
            "co": "Acme",
            "site": "acme.com",
            "emp": "1,200",
            "src": "referral",
        },
        MAP,
    )
    assert res.valid
    assert res.record == {
        "FirstName": "Jane",
        "LastName": "O'Neill",
        "Email": "jane@acme.com",
        "Phone": "+14155550132",
        "Company": "Acme",
        "Website": "https://acme.com",
        "NumberOfEmployees": 1200,
        "LeadSource": "Partner Referral",
    }


@pytest.mark.parametrize(
    "raw,errors",
    [
        ({"last": "Doe", "co": "Acme", "email": "bad@"}, ["Invalid email: bad@"]),
        ({"co": "Acme"}, ["Missing required field: Last Name"]),
        ({"last": "Doe"}, ["Missing required field: Company"]),
    ],
)
def test_transform_validation(raw, errors):
    assert transform_row(raw, MAP).errors == errors


def test_transform_warnings_do_not_block():
    res = transform_row({"last": "Doe", "co": "Acme", "phone": "12", "emp": "lots", "src": "carrier pigeon"}, MAP)
    assert res.valid and len(res.warnings) == 3
    assert res.record["LeadSource"] == "Other" and "NumberOfEmployees" not in res.record


def test_transform_truncates_long_values():
    res = transform_row({"last": "x" * 100, "co": "Acme"}, MAP)
    assert len(res.record["LastName"]) == 80 and res.warnings


@pytest.mark.parametrize(
    "full,expected",
    [
        ("Jane Doe", ("Jane", "Doe")),
        ("Doe, Jane", ("Jane", "Doe")),
        ("Cher", ("", "Cher")),
        ("Mary Ann Smith", ("Mary Ann", "Smith")),
    ],
)
def test_split_full_name(full, expected):
    assert split_full_name(full) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("415.555.0132", "+14155550132"),
        ("1 415 555 0132", "+14155550132"),
        ("+44 20 7946 0958", "+442079460958"),
        ("555-01", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


# -- dedupe ----------------------------------------------------------------------------------


def test_dedupe_merges_missing_fields_into_first_record():
    recs = [
        {"Email": "a@x.com", "LastName": "A", "Company": "X"},
        {"Email": "b@x.com", "LastName": "B", "Company": "X"},
        {"Email": "a@x.com", "LastName": "A", "Company": "X", "Title": "CTO"},
    ]
    merged, groups = dedupe(recs)
    assert list(groups) == [0] and groups[0].duplicates == [2]
    assert merged[0]["Title"] == "CTO" and groups[0].filled_fields == {"Title": 2}


def test_dedupe_key_falls_back_to_name_and_company():
    assert dedupe_key({"FirstName": "Jo", "LastName": "Doe", "Company": "Acme Inc."}) == "name:jo|doe|acmeinc"
    assert dedupe_key({"FirstName": "Jo"}) is None


# -- Salesforce client -----------------------------------------------------------------------


class FakeSession(requests.Session):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, body = self.responses.pop(0)
        resp = requests.Response()
        resp.status_code = status
        resp._content = __import__("json").dumps(body).encode()
        return resp

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def test_soql_quote_escapes():
    assert soql_quote("o'neil\\") == "'o\\'neil\\\\'"


def test_client_credentials_and_composite_create():
    session = FakeSession(
        [
            (200, {"access_token": "tok", "instance_url": "https://acme.my.salesforce.com"}),
            (
                200,
                [
                    {"id": "00Q1", "success": True, "errors": []},
                    {"success": False, "errors": [{"statusCode": "REQUIRED_FIELD_MISSING", "message": "Company"}]},
                ],
            ),
        ]
    )
    sf = SalesforceClient.from_client_credentials("https://acme.my.salesforce.com", "id", "secret", session=session)
    results = sf.create_leads([{"LastName": "A", "Company": "X"}, {"LastName": "B"}])

    assert session.headers["Authorization"] == "Bearer tok"
    method, url, kwargs = session.calls[1]
    assert (method, url) == ("POST", "https://acme.my.salesforce.com/services/data/v61.0/composite/sobjects")
    assert kwargs["json"]["allOrNone"] is False
    assert kwargs["json"]["records"][0]["attributes"] == {"type": "Lead"}
    assert results[0].success and results[0].id == "00Q1"
    assert not results[1].success and "REQUIRED_FIELD_MISSING" in results[1].error


def test_client_batches_200_and_pages_queries():
    session = FakeSession(
        [(200, [{"id": f"x{i}", "success": True} for i in range(200)]), (200, [{"id": "y", "success": True}])]
    )
    sf = SalesforceClient("https://i.example", "tok", session=session)
    assert len(sf.update_leads([{"Id": str(i)} for i in range(201)])) == 201
    assert [c[0] for c in session.calls] == ["PATCH", "PATCH"]

    session = FakeSession(
        [
            (200, {"done": False, "nextRecordsUrl": "/next", "records": [{"Id": "1", "Email": "A@x.com"}]}),
            (200, {"done": True, "records": [{"Id": "2", "Email": "b@x.com"}]}),
        ]
    )
    sf = SalesforceClient("https://i.example", "tok", session=session)
    assert sf.find_leads_by_email(["a@x.com", "b@x.com"]) == {"a@x.com": "1", "b@x.com": "2"}
    assert session.calls[1][1] == "https://i.example/next"
