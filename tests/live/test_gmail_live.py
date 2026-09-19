import base64
import uuid

from tests.live.helpers import api, client


def _send(token, to, subject, body):
    raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode()).decode()
    return api("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", token, {"raw": raw})


def test_gmail_send_is_verified_by_read_back(gmail_token, gmail_to):
    at = client("gmail", gmail_token)
    subject = f"attest live {uuid.uuid4().hex[:8]}"

    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        return _send(gmail_token, to, subject, body)

    send(gmail_to, subject, "sent by the attest live suite")
    v = at.ledger.last().verification
    assert v.level == "verified", v.evidence
    assert v.evidence["checks"]["label:SENT"] and v.evidence["fields"]["subject"]["ok"]
    assert v.evidence["fields"][f"recipient:{gmail_to.lower()}"]["ok"]


def test_gmail_wrong_recipient_is_unverified(gmail_token, gmail_to):
    """The incident Attest exists to catch: the API returns 200, the record disagrees with the intent."""
    at = client("gmail", gmail_token)
    subject = f"attest live mismatch {uuid.uuid4().hex[:8]}"

    @at.action(system="gmail", verb="send", target="to")
    def send(to, subject, body):
        return _send(gmail_token, gmail_to, subject, body)      # actually sent elsewhere than the intent says

    send("someone-else@example.com", subject, "recipient mismatch on purpose")
    v = at.ledger.last().verification
    assert v.level == "unverified", v.evidence
    assert "recipient:someone-else@example.com" in v.evidence["failed"]


def test_gmail_draft_then_labels(gmail_token, gmail_to):
    at = client("gmail", gmail_token)
    subject = f"attest live draft {uuid.uuid4().hex[:8]}"

    @at.action(system="gmail", verb="create", target="draft")
    def draft(to, subject, body):
        raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode()).decode()
        return api("POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts", gmail_token, {"message": {"raw": raw}})

    d = draft(gmail_to, subject, "draft from the attest live suite")
    assert at.ledger.last().verification.level == "verified", at.ledger.last().verification.evidence

    @at.action(system="gmail", verb="update", target="labels")
    def label(message_id, add_labels):
        return api("POST", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
                   gmail_token, {"addLabelIds": add_labels})

    label(d["message"]["id"], ["STARRED"])
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["checks"]["label:+STARRED"], v.evidence
    api("DELETE", f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{d['id']}", gmail_token)
