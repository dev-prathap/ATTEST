from attest import Attest, AutoGate, SqliteLedger
from attest.descriptor import ActionDescriptor as D
from attest.verify.drivers.openapi import OpenApiDriver
from attest.verify.readers import ReadBackError

SPEC = {
    "servers": [{"url": "https://api.someweirdcrm.io/v2"}],
    "paths": {
        "/leads": {"post": {}, "get": {}},
        "/leads/{leadId}": {"get": {}, "patch": {}, "delete": {}},
        "/orgs/{orgId}/deals": {"post": {}},
        "/orgs/{orgId}/deals/{dealId}": {"get": {}, "put": {}},
        "/emails/send": {"post": {}},
    },
}
DB = {}


def http_get(url, params=None):
    key = url.rsplit("/", 1)[-1]
    if key not in DB:
        raise ReadBackError("HTTP 404")
    return DB[key]


def setup_function():
    DB.clear()


def test_read_path_resolution():
    drv = OpenApiDriver(SPEC, http_get)
    assert drv.read_path(D(verb="create", extra={"method": "POST", "url": "https://api.someweirdcrm.io/v2/leads"}), {"id": "L-1"}) == "/leads/L-1"
    assert drv.read_path(D(verb="update", extra={"method": "PATCH", "url": "https://api.someweirdcrm.io/v2/leads/L-1"}), {}) == "/leads/L-1"
    assert drv.read_path(D(verb="create", extra={"method": "POST", "url": "https://api.someweirdcrm.io/v2/orgs/o9/deals"}), {"id": "D-7"}) == "/orgs/o9/deals/D-7"
    assert drv.read_path(D(verb="update", extra={"method": "PUT", "url": "https://api.someweirdcrm.io/v2/orgs/o9/deals/D-7"}), {}) == "/orgs/o9/deals/D-7"
    assert drv.read_path(D(verb="create", extra={"method": "POST", "url": "https://api.someweirdcrm.io/v2/emails/send"}), {"id": "x"}) is None
    assert drv.read_path(D(verb="create", extra={"method": "POST", "url": "https://api.someweirdcrm.io/v2/leads"}), {"ok": True}) is None


def test_yaml_and_file_specs(tmp_path):
    y = "servers:\n  - url: https://x.io/v1\npaths:\n  /things:\n    post: {}\n  /things/{id}:\n    get: {}\n"
    assert OpenApiDriver(y, http_get).read_path(D(verb="create", extra={"method": "POST", "url": "https://x.io/v1/things"}), {"id": 3}) == "/things/3"
    p = tmp_path / "spec.yaml"
    p.write_text(y)
    assert OpenApiDriver(str(p), http_get).base_url == "https://x.io/v1"


def test_end_to_end_verified_and_unverified():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), drivers=[OpenApiDriver(SPEC, http_get)])

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/orgs/o9/deals")
    def create_deal(name, amount):
        DB["D-7"] = {"id": "D-7", "name": name, "amount": amount}
        return {"id": "D-7"}

    create_deal("Acme", 100)
    v = at.ledger.last().verification
    assert v.level == "verified" and v.method == "read-back:openapi" and set(v.evidence["fields"]) == {"id", "name", "amount"}

    @at.action(method="PUT", url="https://api.someweirdcrm.io/v2/orgs/o9/deals/D-7")
    def update_deal(amount):
        return {"ok": True}

    update_deal(999)
    assert at.ledger.last().verification.level == "unverified"

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/emails/send")
    def send(to):
        return {"id": "e1"}

    send("x@y.com")
    assert at.ledger.last().verification.level == "acknowledged"  # no GET in the spec ⇒ no guess


def test_openapi_beats_convention_when_both_present():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), drivers=[OpenApiDriver(SPEC, http_get)], http_get=http_get)

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
    def create(name):
        DB["L-1"] = {"id": "L-1", "name": name}
        return {"id": "L-1"}

    create("N")
    assert at.ledger.last().verification.method == "read-back:openapi"
