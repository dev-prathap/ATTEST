import pytest
from attest_cloud.db import Database
from attest_cloud.main import app, configure
from fastapi.testclient import TestClient


@pytest.fixture
def db():
    return Database("sqlite+pysqlite:///:memory:")


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("ATTEST_CLOUD_BOOTSTRAP_TOKEN", "boot")
    configure(db)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def org(client):
    r = client.post("/v1/orgs", json={"name": "Acme", "domain": "acme.com"}, headers={"X-Bootstrap-Token": "boot"})
    assert r.status_code == 201, r.text
    data = r.json()
    # existing tests assume no plan limits; billing tests reset to `free` explicitly
    client.put("/v1/billing/plan", json={"plan": "pro"},
               headers={"Authorization": f"Bearer {data['api_key']}", "X-Bootstrap-Token": "boot"})
    return {"id": data["org"]["id"], "admin": data["api_key"]}


def auth(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def keys(client, org):
    a = client.post("/v1/keys", json={"name": "agent-1", "role": "agent"}, headers=auth(org["admin"])).json()["api_key"]
    p = client.post("/v1/keys", json={"name": "ram", "role": "approver"}, headers=auth(org["admin"])).json()["api_key"]
    return {"admin": org["admin"], "agent": a, "approver": p}
