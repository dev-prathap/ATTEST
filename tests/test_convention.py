from attest import Attest, AutoGate, SqliteLedger
from attest.descriptor import ActionDescriptor as D
from attest.verify.drivers.convention import ConventionDriver
from attest.verify.readers import ReadBackError

DB = {}


def http_get(url, params=None):
    key = url.rsplit("/", 1)[-1]
    if key not in DB:
        raise ReadBackError("HTTP 404")
    return DB[key]


def setup_function():
    DB.clear()


def test_read_url_rules():
    d = D(verb="create", extra={"method": "POST", "url": "https://api.x.io/v2/leads?x=1"})
    assert ConventionDriver.read_url(d, {"id": "L-1"}) == "https://api.x.io/v2/leads/L-1"
    assert ConventionDriver.read_url(d, {"nothing": 1}) is None
    d = D(verb="update", extra={"method": "PATCH", "url": "https://api.x.io/v2/leads/L-1"})
    assert ConventionDriver.read_url(d, {"ok": True}) == "https://api.x.io/v2/leads/L-1"
    assert ConventionDriver.read_url(D(verb="create"), {"id": 1}) is None


def test_supports():
    drv = ConventionDriver(http_get)
    assert drv.supports(D(verb="create", extra={"url": "https://x/y"}))
    assert not drv.supports(D(verb="create"))
    assert not drv.supports(D(verb="search", extra={"url": "https://x/y"}))
    assert ConventionDriver(lookup=lambda d, i: None).supports(D(verb="update"))
    assert not ConventionDriver().supports(D(verb="create", extra={"url": "https://x/y"}))


def test_unknown_app_create_is_verified_l3():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), http_get=http_get)

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
    def create_lead(name, email):
        DB["L-991"] = {"id": "L-991", "name": name, "email": email}
        return {"id": "L-991"}

    create_lead("Arun", "arun@newco.com")
    v = at.ledger.last().verification
    assert v.level == "verified" and v.method == "read-back:convention"
    assert set(v.evidence["fields"]) == {"id", "name", "email"}


def test_unknown_app_update_contradiction_is_unverified():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), http_get=http_get)
    DB["L-1"] = {"id": "L-1", "stage": "new"}

    @at.action(method="PATCH", url="https://api.someweirdcrm.io/v2/leads/L-1")
    def update_lead(stage):
        return {"ok": True}  # vendor said yes but did not persist

    update_lead("won")
    v = at.ledger.last().verification
    assert v.level == "unverified" and v.evidence["failed"] == ["stage"]


def test_existence_only_is_acknowledged_not_verified():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), http_get=http_get)
    DB["L-2"] = {"id": "L-2", "unrelated": 1}

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
    def create_lead(blob):
        return {"id": "L-2"}

    create_lead({"nested": "not comparable"})
    v = at.ledger.last().verification
    assert v.level == "acknowledged" and v.evidence["exists"] is True and v.matched is None


def test_404_degrades_to_ack_with_error():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), http_get=http_get)

    @at.action(method="POST", url="https://api.someweirdcrm.io/v2/leads")
    def create_lead(name):
        return {"id": "GHOST"}

    create_lead("x")
    v = at.ledger.last().verification
    assert v.level == "acknowledged" and "nothing to compare" in v.evidence["check_error"]


def test_lookup_callable_for_sdk_style():
    store = {"7": {"id": "7", "title": "Hello"}}
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), drivers=[ConventionDriver(lookup=lambda d, i: store.get(i))])

    @at.action(system="notion", verb="create", target="page")
    def create_page(title):
        return {"id": "7"}

    create_page("Hello")
    assert at.ledger.last().verification.level == "verified"
    create_page("Other")
    assert at.ledger.last().verification.level == "unverified"


def test_per_action_http_get_and_bearer_token_string():
    at = Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate())
    DB["L-3"] = {"id": "L-3", "name": "N"}

    @at.action(method="POST", url="https://api.x.io/v2/leads", http_get=http_get)
    def create(name):
        return {"id": "L-3"}

    create("N")
    assert at.ledger.last().verification.level == "verified"
    drv = ConventionDriver("bearer-token-string")
    assert drv.reader is not None and drv.reader.token == "bearer-token-string"
