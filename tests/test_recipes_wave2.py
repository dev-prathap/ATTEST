"""Wave-2 recipes against client-shaped fakes: Calendar, Drive, Docs, Sheets, Notion, Linear, Microsoft 365."""
import pytest

from attest import Attest, AutoGate, SqliteLedger
from attest.descriptor import ActionDescriptor as D
from attest.verify import recipes


def client_for(system, fake):
    return Attest(ledger=SqliteLedger(":memory:"), gate=AutoGate(), actor="ram@acme.com", readers={system: fake})


class _Exec:
    def __init__(self, data):
        self.data = data

    def execute(self):
        if self.data is None:
            raise Exception("HttpError 404")
        return self.data


# ── Calendar ──────────────────────────────────────────────────────────────────
class FakeCalendar:
    def __init__(self):
        self.store = {}

    def events(self):
        return self

    def get(self, calendarId, eventId):
        return _Exec(self.store.get((calendarId, eventId)))


def test_calendar_event_verified_and_mismatch():
    cal = FakeCalendar()
    at = client_for("calendar", cal)

    @at.action(system="calendar", verb="create", target="event")
    def create(summary, start, attendees):
        cal.store[("primary", "e1")] = {"id": "e1", "status": "confirmed", "summary": summary,
                                        "start": {"dateTime": start}, "attendees": [{"email": a} for a in attendees]}
        return {"id": "e1"}

    create("Kickoff", "2026-10-01T10:00:00+01:00", ["arun@newco.com"])
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["summary"]["ok"] and v.evidence["fields"]["attendee:arun@newco.com"]["ok"]

    @at.action(system="calendar", verb="update", target="event")
    def update(event_id, summary):
        cal.store[("primary", event_id)]["status"] = "cancelled"
        return {"id": event_id}

    update("e1", "Kickoff")
    v = at.ledger.last().verification
    assert v.level == "unverified" and "status:confirmed" in v.evidence["failed"]


# ── Drive / Docs / Sheets ─────────────────────────────────────────────────────
class FakeDrive:
    def __init__(self):
        self.files_, self.perms = {}, {}

    def files(self):
        return self

    def permissions(self):
        return self

    def get(self, fileId, fields=None, supportsAllDrives=None):
        return _Exec(self.files_.get(fileId))

    def list(self, fileId, fields=None, supportsAllDrives=None):
        return _Exec({"permissions": self.perms.get(fileId, [])})


def test_drive_file_and_share():
    drv = FakeDrive()
    at = client_for("drive", drv)

    @at.action(system="drive", verb="create", target="folder")
    def mkdir(name, parent):
        drv.files_["f1"] = {"id": "f1", "name": name, "parents": [parent], "trashed": False}
        return {"id": "f1"}

    mkdir("Proposals", "root")
    assert at.ledger.last().verification.level == "verified"

    @at.action(system="drive", verb="share", target="file_id")
    def share(file_id, email, role):
        drv.perms[file_id] = [{"emailAddress": email.upper(), "role": "reader"}]
        return {"id": "p1"}

    share("f1", "arun@newco.com", "writer")
    v = at.ledger.last().verification
    assert v.level == "unverified" and v.evidence["fields"]["role"]["ok"] is False and v.evidence["fields"]["shared:arun@newco.com"]["ok"]


class FakeDocs:
    def __init__(self):
        self.docs = {}

    def documents(self):
        return self

    def get(self, documentId):
        return _Exec(self.docs.get(documentId))


def test_docs_create_and_append():
    docs = FakeDocs()
    at = client_for("docs", docs)

    @at.action(system="docs", verb="create", target="document")
    def create(title):
        docs.docs["d1"] = {"documentId": "d1", "title": title, "body": {"content": []}}
        return {"documentId": "d1"}

    create("Q4 plan")
    assert at.ledger.last().verification.level == "verified"

    @at.action(system="docs", verb="update", target="document")
    def append(document_id, text):
        docs.docs[document_id]["body"] = {"content": [{"paragraph": {"elements": [{"textRun": {"content": "old " + text}}]}}]}
        return {"documentId": document_id}

    append("d1", "Added at the end.")
    assert at.ledger.last().verification.evidence["checks"]["text:present"]

    @at.action(system="docs", verb="update", target="document")
    def append_lost(document_id, text):
        return {"documentId": document_id}

    append_lost("d1", "Never written")
    assert at.ledger.last().verification.level == "unverified"


class FakeSheets:
    def __init__(self):
        self.sheets, self.vals = {}, {}

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, fields=None, range=None):
        if range:
            return _Exec({"values": self.vals.get((spreadsheetId, range), [])})
        return _Exec(self.sheets.get(spreadsheetId))


def test_sheets_create_and_values():
    sh = FakeSheets()
    at = client_for("sheets", sh)

    @at.action(system="sheets", verb="create", target="spreadsheet")
    def create(title):
        sh.sheets["s1"] = {"spreadsheetId": "s1", "properties": {"title": title}}
        return {"spreadsheetId": "s1"}

    create("Pipeline")
    assert at.ledger.last().verification.level == "verified"

    @at.action(system="sheets", verb="update", target="values")
    def write(spreadsheet_id, range, values):
        sh.vals[(spreadsheet_id, range)] = [["Acme", 1000], ["Newco", "2000"]]
        return {"updatedRows": 2}

    write("s1", "Sheet1!A1:B2", [["Acme", "1000"], ["Newco", 2000]])
    assert at.ledger.last().verification.level == "verified"
    write("s1", "Sheet1!A1:B2", [["Other", 1]])
    assert at.ledger.last().verification.level == "unverified"


# ── Notion ────────────────────────────────────────────────────────────────────
class FakeNotion:
    def __init__(self):
        self.pages_, self.dbs = {}, {}
        self.pages = self
        self.databases = self

    def retrieve(self, page_id=None, database_id=None):
        data = self.pages_.get(page_id) if page_id else self.dbs.get(database_id)
        if data is None:
            raise Exception("404 object_not_found")
        return data


def test_notion_page_properties_and_database():
    n = FakeNotion()
    at = client_for("notion", n)

    @at.action(system="notion", verb="create", target="page")
    def create(parent, properties):
        n.pages_["p1"] = {"id": "p1", "archived": False, "parent": {"database_id": parent["database_id"]}, "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Launch plan"}]},
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Owner": {"type": "rich_text", "rich_text": [{"plain_text": "Ram"}]}}}
        return {"id": "p1"}

    create({"database_id": "db-1"}, {"Name": {"title": [{"text": {"content": "Launch plan"}}]},
                                     "Status": {"status": {"name": "In progress"}}})
    v = at.ledger.last().verification
    assert v.level == "verified" and set(v.evidence["fields"]) == {"Name", "Status", "parent.database_id"}

    @at.action(system="notion", verb="update", target="page")
    def update(page_id, properties):
        return {"id": page_id}  # not persisted

    update("p1", {"Status": {"status": {"name": "Done"}}})
    assert at.ledger.last().verification.level == "unverified"

    @at.action(system="notion", verb="create", target="database")
    def mkdb(parent, title):
        n.dbs["db-2"] = {"id": "db-2", "title": [{"plain_text": "Deals"}]}
        return {"id": "db-2"}

    mkdb({"page_id": "p1"}, [{"text": {"content": "Deals"}}])
    assert at.ledger.last().verification.level == "verified"


# ── Linear ────────────────────────────────────────────────────────────────────
class FakeLinear:
    def __init__(self):
        self.issues, self.projects, self.comments = {}, {}, {}

    def query(self, gql, variables):
        iid = variables["id"]
        if "issue(" in gql:
            return {"data": {"issue": self.issues.get(iid)}}
        if "project(" in gql:
            return {"data": {"project": self.projects.get(iid)}}
        return {"data": {"comment": self.comments.get(iid)}}


def test_linear_issue_project_comment():
    ln = FakeLinear()
    at = client_for("linear", ln)

    @at.action(system="linear", verb="create", target="issue")
    def create_issue(title, team_id, priority):
        ln.issues["i1"] = {"id": "i1", "title": title, "priority": priority, "state": {"name": "Todo"}, "team": {"id": team_id}}
        return {"issueCreate": {"success": True, "issue": {"id": "i1"}}}

    create_issue("Fix login", "T1", 2)
    v = at.ledger.last().verification
    assert v.level == "verified" and set(v.evidence["fields"]) == {"title", "priority", "team"}

    @at.action(system="linear", verb="update", target="issue")
    def move(issue_id, state):
        return {"issueUpdate": {"success": True}}

    move("i1", "Done")
    assert at.ledger.last().verification.level == "unverified"

    @at.action(system="linear", verb="create", target="comment")
    def comment(issue_id, body):
        ln.comments["c1"] = {"id": "c1", "body": body, "issue": {"id": issue_id}}
        return {"commentCreate": {"comment": {"id": "c1"}}}

    comment("i1", "Looks good")
    assert at.ledger.last().verification.level == "verified"

    @at.action(system="linear", verb="create", target="project")
    def project(name):
        ln.projects["pr1"] = {"id": "pr1", "name": name}
        return {"projectCreate": {"project": {"id": "pr1"}}}

    project("Q4")
    assert at.ledger.last().verification.level == "verified"


def test_linear_graphql_error_degrades():
    class Broken:
        def query(self, gql, variables):
            return {"errors": [{"message": "Entity not found"}]}

    at = client_for("linear", Broken())

    @at.action(system="linear", verb="create", target="issue")
    def create_issue(title):
        return {"issueCreate": {"issue": {"id": "x"}}}

    create_issue("T")
    v = at.ledger.last().verification
    assert v.level == "acknowledged" and "Entity not found" in v.evidence["check_error"]


# ── Microsoft 365 ─────────────────────────────────────────────────────────────
class FakeGraph:
    def __init__(self):
        self.sent, self.events, self.msgs = [], {}, {}

    def __call__(self, path, params):
        if path.startswith("me/mailFolders/sentitems"):
            subj = params["$filter"].split("'")[1].replace("''", "'")
            return {"value": [m for m in self.sent if m["subject"] == subj]}
        if path.startswith("me/events/"):
            ev = self.events.get(path.rsplit("/", 1)[-1])
            if ev is None:
                from attest.verify.readers import ReadBackError
                raise ReadBackError("HTTP 404")
            return ev
        if path.startswith("teams/"):
            return self.msgs.get(path.rsplit("/", 1)[-1])
        return None


def test_outlook_send_found_in_sentitems_or_not():
    g = FakeGraph()
    at = client_for("outlook", g)

    @at.action(system="outlook", verb="send", target="to")
    def send(to, subject):
        g.sent.append({"id": "AAMk1", "subject": subject, "toRecipients": [{"emailAddress": {"address": to.upper()}}]})
        return {"status": 202}

    send("arun@newco.com", "Q4 proposal")
    v = at.ledger.last().verification
    assert v.level == "verified" and v.evidence["fields"]["recipient:arun@newco.com"]["ok"]

    @at.action(system="outlook", verb="send", target="to")
    def send_wrong(to, subject):
        g.sent.append({"id": "AAMk2", "subject": subject, "toRecipients": [{"emailAddress": {"address": "else@x.com"}}]})
        return {"status": 202}

    send_wrong("arun@newco.com", "Other")
    assert at.ledger.last().verification.level == "unverified"

    @at.action(system="outlook", verb="send", target="to")
    def send_lost(to, subject):
        return {"status": 202}

    send_lost("arun@newco.com", "Never sent")
    assert at.ledger.last().verification.level == "acknowledged"  # nothing found ⇒ cannot compare


def test_outlook_event_and_teams_message():
    g = FakeGraph()
    at = client_for("outlook", g)

    @at.action(system="outlook", verb="create", target="event")
    def create(subject, start, attendees):
        g.events["ev1"] = {"id": "ev1", "subject": subject, "isCancelled": False, "start": {"dateTime": start},
                           "attendees": [{"emailAddress": {"address": a}} for a in attendees]}
        return {"id": "ev1"}

    create("Sync", "2026-10-01T10:00:00.0000000", ["arun@newco.com"])
    assert at.ledger.last().verification.level == "verified"

    at2 = client_for("teams", g)

    @at2.action(system="teams", verb="send", target="channel_id")
    def post(team_id, channel_id, content):
        g.msgs["m1"] = {"id": "m1", "body": {"content": f"<div>{content}</div>"}}
        return {"id": "m1"}

    post("T1", "C1", "Deploy done ✅")
    assert at2.ledger.last().verification.level == "verified"


# ── registry sanity ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("system,verb,target,name", [
    ("calendar", "create", "event", "calendar.event"), ("drive", "share", "file", "drive.share"),
    ("drive", "create", "folder", "drive.file"), ("docs", "update", "document", "docs.document"),
    ("sheets", "create", "spreadsheet", "sheets.spreadsheet"), ("notion", "create", "database", "notion.database"),
    ("notion", "update", "page", "notion.page"), ("linear", "create", "issue", "linear.issue"),
    ("linear", "create", "comment", "linear.comment"), ("outlook", "send", None, "outlook.send"),
    ("outlook", "create", "event", "outlook.event"), ("teams", "send", "channel", "teams.message"),
])
def test_recipe_selection(system, verb, target, name):
    assert recipes.find(D(system=system, verb=verb, target=target), {}).name == name
