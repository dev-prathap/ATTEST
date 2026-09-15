"""P3.5 OIDC SSO sessions; P3.6 digest endpoint."""
from attest_cloud import oidc
from attest_cloud.main import app
from conftest import auth
from test_api import entry


def _sso_env(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "csec")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://cloud/auth/callback")
    monkeypatch.setenv("ATTEST_SESSION_SECRET", "sess")


def fake_idp(email="priya@acme.com"):
    def fetch(method, url, body, headers):
        if url.endswith("openid-configuration"):
            return {"authorization_endpoint": "https://idp.example/auth", "token_endpoint": "https://idp.example/token",
                    "userinfo_endpoint": "https://idp.example/userinfo"}
        if url.endswith("/token"):
            assert b"code=abc" in body and b"client_secret=csec" in body
            return {"access_token": "at"}
        if url.endswith("/userinfo"):
            assert headers["Authorization"] == "Bearer at"
            return {"email": email, "name": "Priya"}
        raise AssertionError(url)
    return fetch


def test_sso_disabled_by_default(client):
    assert client.get("/auth/login", follow_redirects=False).status_code == 503
    assert client.get("/auth/me").status_code == 401


def test_sso_login_callback_session_and_roles(client, keys, monkeypatch):
    _sso_env(monkeypatch)
    app.state.oidc_fetch = fake_idp()
    client.put("/v1/settings", json={"sso_admins": ["ram@acme.com"], "sso_domains": ["acme.io"]}, headers=auth(keys["admin"]))
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://idp.example/auth?") and "attest_oidc_state" in r.cookies
    state = r.cookies["attest_oidc_state"]
    bad = client.get("/auth/callback?code=abc&state=wrong", follow_redirects=False)
    assert bad.status_code == 401
    r = client.get(f"/auth/callback?code=abc&state={state}", cookies={"attest_oidc_state": state}, follow_redirects=False)
    assert r.status_code == 302 and oidc.COOKIE in r.cookies
    sess = r.cookies[oidc.COOKIE]
    me = client.get("/auth/me", cookies={oidc.COOKIE: sess}).json()
    assert me["email"] == "priya@acme.com" and me["role"] == "approver"
    # the session acts as an approver principal on the API
    client.post("/v1/attest", json={"entries": [entry(1)]}, headers=auth(keys["agent"]))
    assert client.get("/v1/ledger", cookies={oidc.COOKIE: sess}).status_code == 200
    assert client.get("/v1/keys", cookies={oidc.COOKIE: sess}).status_code == 403
    # an admin by email
    app.state.oidc_fetch = fake_idp("ram@acme.com")
    r = client.get(f"/auth/callback?code=abc&state={state}", cookies={"attest_oidc_state": state}, follow_redirects=False)
    admin_sess = r.cookies[oidc.COOKIE]
    assert client.get("/auth/me", cookies={oidc.COOKIE: admin_sess}).json()["role"] == "admin"
    assert client.get("/v1/keys", cookies={oidc.COOKIE: admin_sess}).status_code == 200
    # unknown domain is refused; tampered cookie is ignored
    app.state.oidc_fetch = fake_idp("eve@evil.io")
    assert client.get(f"/auth/callback?code=abc&state={state}", cookies={"attest_oidc_state": state}, follow_redirects=False).status_code == 403
    assert client.get("/auth/me", cookies={oidc.COOKIE: sess[:-4] + "0000"}).status_code == 401
    assert client.post("/auth/logout", follow_redirects=False).status_code == 302
    del app.state.oidc_fetch


def test_digest_endpoint(client, keys):
    e1, e2 = entry(1), entry(2)
    e2["verification"] = {"level": "unverified", "evidence": {"failed": ["subject"]}}
    client.post("/v1/attest", json={"entries": [e1, e2]}, headers=auth(keys["agent"]))
    d = client.get("/v1/digest?since_hours=24", headers=auth(keys["agent"])).json()
    assert d["summary"]["actions"] == 2 and d["summary"]["by_level"]["unverified"] == 1 and d["summary"]["unverified"][0]["failed"] == ["subject"]
    assert client.get("/v1/digest?agent=nobody", headers=auth(keys["agent"])).json()["summary"]["actions"] == 0
