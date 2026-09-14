import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from attest.verify.readers import GmailReader, HttpReader, HubSpotReader, ReadBackError, SlackReader, build, http_get


class FakeGmailService:
    def __init__(self, store):
        self.store = store
        self.calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return self

    def get(self, userId, id, format=None, metadataHeaders=None):
        self.calls.append((id, format, metadataHeaders))
        data = self.store[id]
        return type("Req", (), {"execute": lambda s: data})()


def test_gmail_reader_with_service_object():
    svc = FakeGmailService({"m1": {"id": "m1", "labelIds": ["SENT"]}})
    r = GmailReader(svc)
    assert r.message("m1")["labelIds"] == ["SENT"] and svc.calls[0][1] == "metadata"
    assert r.message_labels("m1") and svc.calls[-1][1] == "minimal"


def test_gmail_reader_with_fetch_callable():
    seen = []
    def fetch(path, params):
        seen.append((path, params))
        return {"id": "m1"}
    assert GmailReader(fetch=fetch).message("m1") == {"id": "m1"}
    assert seen[0][0] == "users/me/messages/m1" and seen[0][1]["format"] == "metadata"


def test_reader_without_credentials_raises_readback_error():
    with pytest.raises(ReadBackError):
        GmailReader().message("m1")


def test_reader_wraps_client_exceptions():
    class Bad:
        def users(self):
            raise RuntimeError("boom")
    with pytest.raises(ReadBackError, match="boom"):
        GmailReader(Bad()).message("m1")


def test_slack_reader_history_and_replies():
    class WC:
        def conversations_history(self, channel, latest, inclusive, limit):
            return {"ok": True, "messages": [{"ts": "1.5", "text": "hi"}]} if latest == "1.5" else {"ok": True, "messages": []}
        def conversations_replies(self, channel, ts, limit):
            return {"ok": True, "messages": [{"ts": ts, "text": "reply"}]}
        def conversations_info(self, channel):
            return {"ok": True, "channel": {"id": channel, "name": "general"}}
    r = SlackReader(WC())
    assert r.message("C1", "1.5")["text"] == "hi"
    assert r.message("C1", "2.0")["text"] == "reply"
    assert r.channel("C1")["name"] == "general"


def test_slack_reader_error_response():
    class WC:
        def conversations_history(self, **kw):
            return {"ok": False, "error": "channel_not_found"}
    with pytest.raises(ReadBackError, match="channel_not_found"):
        SlackReader(WC()).message("C1", "1")


def test_hubspot_reader_with_client_and_404():
    class Obj:
        def to_dict(self):
            return {"id": "1", "properties": {"dealname": "Acme"}}
    class Api:
        def get_by_id(self, object_type, object_id, properties=None):
            if object_id == "404":
                raise Exception("(404) Not Found")
            return Obj()
    class Client:
        class crm:
            class objects:
                basic_api = Api()
    r = HubSpotReader(Client())
    assert r.object("deals", "1", ["dealname"])["properties"]["dealname"] == "Acme"
    assert r.object("deals", "404", []) is None


def _serve(handler_body):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = handler_body(self.path, self.headers)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_http_get_bearer_token_and_errors():
    seen = {}
    def body(path, headers):
        seen["auth"], seen["path"] = headers.get("Authorization"), path
        if "missing" in path:
            return 404, {"error": "nope"}
        return 200, {"id": "L-1", "email": "a@b.com"}
    srv, base = _serve(body)
    try:
        assert http_get(f"{base}/v2/leads/L-1", {"properties": "email"}, token="tok")["id"] == "L-1"
        assert seen["auth"] == "Bearer tok" and "properties=email" in seen["path"]
        with pytest.raises(ReadBackError, match="HTTP 404"):
            http_get(f"{base}/v2/leads/missing", token="tok")
        assert HttpReader(token="tok").get(f"{base}/v2/leads/missing") is None
        assert HubSpotReader(fetch=lambda p, q: http_get(f"{base}/{p}", q)).object("deals", "1", ["x"])["id"] == "L-1"
    finally:
        srv.shutdown()


def test_build_coerces_values():
    assert isinstance(build("gmail", "ya29.token"), GmailReader) and build("gmail", "ya29.token").token == "ya29.token"
    assert isinstance(build("slack", lambda p, q: {}), SlackReader)
    assert isinstance(build("hubspot", object()), HubSpotReader)
    r = HttpReader(token="t")
    assert build("http", r) is r
    assert build("someweird", "tok").system == "http"
