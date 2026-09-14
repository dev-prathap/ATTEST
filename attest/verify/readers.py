"""Pass-through readers (doc 03 §5): the SDK reads back with the *caller's* client or token, in-process.
Nothing here talks to Attest Cloud and no credential leaves the process.

Each reader accepts, in order of preference:
  client=   the vendor SDK object the agent already holds (googleapiclient resource, slack_sdk WebClient,
            hubspot Client) — duck-typed, no import of the vendor package
  fetch=    a callable `fetch(path_or_method, params) -> dict` backed by any HTTP client
  token=    a bearer token; the reader issues the GET itself with urllib (no extra dependency)
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Fetch = Callable[[str, dict[str, Any]], Any]


class ReadBackError(Exception):
    """The read could not be performed (auth, network, 404). Never a contradiction."""


def _to_dict(obj: Any) -> Any:
    if obj is None or isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    for attr in ("to_dict", "model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                continue
    data = getattr(obj, "data", None)
    if isinstance(data, dict):
        return data
    if hasattr(obj, "__getitem__") and hasattr(obj, "get"):
        return dict(obj)
    return vars(obj) if hasattr(obj, "__dict__") else obj


def http_get(url: str, params: dict[str, Any] | None = None, *, token: str | None = None,
             headers: dict[str, str] | None = None, timeout: float = 20.0) -> Any:
    """Tiny GET with bearer auth, JSON response. Raises ReadBackError on any failure."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None},
                                                                     doseq=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - caller-supplied API host
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ReadBackError(f"GET {url.split('?')[0]} → HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ReadBackError(f"GET {url.split('?')[0]} failed: {e}") from e
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        raise ReadBackError("non-JSON response") from e


def bearer(token: str, base: str = "") -> Fetch:
    """`fetch(path, params)` over a base URL with a bearer token — the pass-through default."""
    def fetch(path: str, params: dict[str, Any]) -> Any:
        url = path if path.startswith("http") else base.rstrip("/") + "/" + path.lstrip("/")
        return http_get(url, params, token=token)
    return fetch


class BaseReader:
    system = "unknown"
    base_url = ""
    client_markers: tuple[str, ...] = ()  # attributes that identify a vendor client object (vs. a fetch callable)

    def __init__(self, client: Any = None, *, fetch: Fetch | None = None, token: str | None = None):
        if client is not None and isinstance(client, str) and token is None and fetch is None:
            client, token = None, client  # a bare string is a token
        self.client, self._fetch, self.token = client, fetch, token
        if self._fetch is None and self.token:
            self._fetch = bearer(self.token, self.base_url)

    def fetch(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._fetch is None:
            raise ReadBackError(f"{self.system}: no client, fetch or token configured for read-back")
        try:
            return _to_dict(self._fetch(path, params or {}))
        except ReadBackError:
            raise
        except Exception as e:
            raise ReadBackError(f"{self.system}: {type(e).__name__}: {e}") from e

    def _call(self, fn: Callable[..., Any], **kw: Any) -> Any:
        try:
            return _to_dict(fn(**kw))
        except Exception as e:
            raise ReadBackError(f"{self.system}: {type(e).__name__}: {e}") from e


class GmailReader(BaseReader):
    system = "gmail"
    client_markers = ("users",)
    base_url = "https://gmail.googleapis.com/gmail/v1/"

    def message(self, message_id: str, *, headers: tuple[str, ...] = ("To", "Cc", "Subject", "From")) -> dict:
        if self.client is not None and hasattr(self.client, "users"):
            return self._call(lambda: self.client.users().messages().get(
                userId="me", id=message_id, format="metadata", metadataHeaders=list(headers)).execute())
        return self.fetch(f"users/me/messages/{message_id}", {"format": "metadata", "metadataHeaders": list(headers)})

    def message_labels(self, message_id: str) -> dict:
        if self.client is not None and hasattr(self.client, "users"):
            return self._call(lambda: self.client.users().messages().get(
                userId="me", id=message_id, format="minimal").execute())
        return self.fetch(f"users/me/messages/{message_id}", {"format": "minimal"})

    def draft(self, draft_id: str) -> dict:
        if self.client is not None and hasattr(self.client, "users"):
            return self._call(lambda: self.client.users().drafts().get(
                userId="me", id=draft_id, format="metadata").execute())
        return self.fetch(f"users/me/drafts/{draft_id}", {"format": "metadata"})


class SlackReader(BaseReader):
    system = "slack"
    client_markers = ("conversations_history", "conversations_info")
    base_url = "https://slack.com/api/"

    def message(self, channel: str, ts: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "conversations_history"):
            data = self._call(self.client.conversations_history, channel=channel, latest=ts, inclusive=True, limit=1)
        else:
            data = self.fetch("conversations.history",
                              {"channel": channel, "latest": ts, "inclusive": "true", "limit": 1})
        if not data.get("ok", True):
            raise ReadBackError(f"slack: {data.get('error')}")
        msgs = data.get("messages") or []
        if not msgs or str(msgs[0].get("ts")) != str(ts):
            if self.client is not None and hasattr(self.client, "conversations_replies"):  # threaded reply
                data = self._call(self.client.conversations_replies, channel=channel, ts=ts, limit=1)
                msgs = [m for m in data.get("messages") or [] if str(m.get("ts")) == str(ts)]
            else:
                return None
        return msgs[0] if msgs else None

    def channel(self, channel: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "conversations_info"):
            data = self._call(self.client.conversations_info, channel=channel)
        else:
            data = self.fetch("conversations.info", {"channel": channel})
        if not data.get("ok", True):
            raise ReadBackError(f"slack: {data.get('error')}")
        return data.get("channel")


class HubSpotReader(BaseReader):
    system = "hubspot"
    client_markers = ("crm",)
    base_url = "https://api.hubapi.com/"

    def object(self, object_type: str, object_id: str, properties: list[str]) -> dict | None:
        if self.client is not None and hasattr(self.client, "crm"):
            api = getattr(getattr(self.client.crm, "objects", None), "basic_api", None)
            if api is None:
                raise ReadBackError("hubspot: client has no crm.objects.basic_api")
            try:
                return self._call(api.get_by_id, object_type=object_type, object_id=object_id,
                                  properties=properties or None)
            except ReadBackError as e:
                if "404" in str(e):
                    return None
                raise
        try:
            return self.fetch(f"crm/v3/objects/{object_type}/{object_id}", {"properties": ",".join(properties)}
                              if properties else {})
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise


class HttpReader(BaseReader):
    """Generic REST reader for the convention driver: `get(url, params)` with the caller's auth."""

    system = "http"

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self.fetch(url, params)
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise


READERS: dict[str, type[BaseReader]] = {"gmail": GmailReader, "slack": SlackReader, "hubspot": HubSpotReader,
                                        "http": HttpReader}


def build(system: str, value: Any) -> BaseReader:
    """Coerce whatever the customer passed for a system into a reader: a reader, a client, a token, a callable."""
    if isinstance(value, BaseReader):
        return value
    cls = READERS.get(system, HttpReader)
    if isinstance(value, str):
        return cls(token=value)
    if callable(value) and not any(hasattr(value, m) for m in cls.client_markers):
        return cls(fetch=value)
    return cls(client=value)


def build_all(readers: dict[str, Any] | None) -> dict[str, BaseReader]:
    return {sys_: build(sys_, v) for sys_, v in (readers or {}).items()}


# ── wave 2 readers (P2.1) ─────────────────────────────────────────────────────
class GoogleCalendarReader(BaseReader):
    system = "calendar"
    client_markers = ("events",)
    base_url = "https://www.googleapis.com/calendar/v3/"

    def event(self, event_id: str, calendar_id: str = "primary") -> dict | None:
        if self.client is not None and hasattr(self.client, "events"):
            return self._call(lambda: self.client.events().get(calendarId=calendar_id, eventId=event_id).execute())
        try:
            return self.fetch(f"calendars/{calendar_id}/events/{event_id}")
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise


class GoogleDriveReader(BaseReader):
    system = "drive"
    client_markers = ("files", "permissions")
    base_url = "https://www.googleapis.com/drive/v3/"
    FIELDS = "id,name,mimeType,parents,trashed,webViewLink,modifiedTime"
    PERM_FIELDS = "permissions(id,emailAddress,role,type,domain)"

    def file(self, file_id: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "files"):
            return self._call(lambda: self.client.files().get(fileId=file_id, fields=self.FIELDS,
                                                              supportsAllDrives=True).execute())
        try:
            return self.fetch(f"files/{file_id}", {"fields": self.FIELDS, "supportsAllDrives": "true"})
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise

    def permissions(self, file_id: str) -> list[dict]:
        if self.client is not None and hasattr(self.client, "permissions"):
            out = self._call(lambda: self.client.permissions().list(
                fileId=file_id, fields=self.PERM_FIELDS, supportsAllDrives=True).execute())
        else:
            out = self.fetch(f"files/{file_id}/permissions", {"fields": self.PERM_FIELDS, "supportsAllDrives": "true"})
        return list((out or {}).get("permissions") or [])


class GoogleDocsReader(BaseReader):
    system = "docs"
    client_markers = ("documents",)
    base_url = "https://docs.googleapis.com/v1/"

    def document(self, document_id: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "documents"):
            return self._call(lambda: self.client.documents().get(documentId=document_id).execute())
        try:
            return self.fetch(f"documents/{document_id}")
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise


class GoogleSheetsReader(BaseReader):
    system = "sheets"
    client_markers = ("spreadsheets",)
    base_url = "https://sheets.googleapis.com/v4/"
    FIELDS = "spreadsheetId,properties.title,sheets.properties.title"

    def spreadsheet(self, spreadsheet_id: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "spreadsheets"):
            return self._call(lambda: self.client.spreadsheets().get(
                spreadsheetId=spreadsheet_id, fields=self.FIELDS).execute())
        try:
            return self.fetch(f"spreadsheets/{spreadsheet_id}", {"fields": self.FIELDS})
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise

    def values(self, spreadsheet_id: str, range_: str) -> list[list]:
        if self.client is not None and hasattr(self.client, "spreadsheets"):
            out = self._call(lambda: self.client.spreadsheets().values().get(spreadsheetId=spreadsheet_id,
                                                                            range=range_).execute())
        else:
            out = self.fetch(f"spreadsheets/{spreadsheet_id}/values/{range_}")
        return list((out or {}).get("values") or [])


class NotionReader(BaseReader):
    system = "notion"
    client_markers = ("pages", "databases")
    base_url = "https://api.notion.com/v1/"
    VERSION = "2022-06-28"

    def __init__(self, client: Any = None, *, fetch: Fetch | None = None, token: str | None = None):
        super().__init__(client, fetch=fetch, token=token)
        if fetch is None and self.token:
            tok = self.token

            def _fetch(path: str, params: dict[str, Any]) -> Any:
                return http_get(self.base_url + path.lstrip("/"), params, token=tok,
                                headers={"Notion-Version": self.VERSION})
            self._fetch = _fetch

    def page(self, page_id: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "pages"):
            return self._call(lambda: self.client.pages.retrieve(page_id=page_id))
        try:
            return self.fetch(f"pages/{page_id}")
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise

    def database(self, database_id: str) -> dict | None:
        if self.client is not None and hasattr(self.client, "databases"):
            return self._call(lambda: self.client.databases.retrieve(database_id=database_id))
        try:
            return self.fetch(f"databases/{database_id}")
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise


class LinearReader(BaseReader):
    """Linear is GraphQL: reads are POSTs. `fetch(query, variables)` for callables; token ⇒ urllib POST."""

    system = "linear"
    base_url = "https://api.linear.app/graphql"
    client_markers = ("query",)

    def query(self, gql: str, variables: dict[str, Any]) -> dict:
        if self.client is not None and hasattr(self.client, "query"):
            out = self._call(lambda: self.client.query(gql, variables))
        elif self._fetch is not None and not self.token:
            out = self.fetch(gql, variables)
        elif self.token:
            body = json.dumps({"query": gql, "variables": variables}).encode()
            req = urllib.request.Request(self.base_url, data=body, method="POST",
                                         headers={"Authorization": self.token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
                    out = json.loads(r.read())
            except urllib.error.HTTPError as e:
                raise ReadBackError(f"linear: HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                raise ReadBackError(f"linear: {e}") from e
        else:
            raise ReadBackError("linear: no client, fetch or token configured for read-back")
        if isinstance(out, dict) and out.get("errors"):
            raise ReadBackError(f"linear: {out['errors'][0].get('message')}")
        return (out or {}).get("data") or out or {}

    def issue(self, issue_id: str) -> dict | None:
        data = self.query("query($id: String!) { issue(id: $id) { id identifier title description priority "
                          "state { name } assignee { id email } team { id key } } }", {"id": issue_id})
        return data.get("issue")

    def project(self, project_id: str) -> dict | None:
        return self.query("query($id: String!) { project(id: $id) { id name description state } }",
                          {"id": project_id}).get("project")

    def comment(self, comment_id: str) -> dict | None:
        return self.query("query($id: String!) { comment(id: $id) { id body issue { id } } }",
                          {"id": comment_id}).get("comment")


class GraphReader(BaseReader):
    """Microsoft Graph (Outlook / Teams / OneDrive / SharePoint) over the caller's token or fetch callable."""

    system = "outlook"
    base_url = "https://graph.microsoft.com/v1.0/"

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self.fetch(path, params)
        except ReadBackError as e:
            if "404" in str(e):
                return None
            raise

    def sent_messages(self, subject: str, top: int = 10) -> list[dict]:
        safe = subject.replace("'", "''")
        out = self.get("me/mailFolders/sentitems/messages",
                       {"$filter": f"subject eq '{safe}'", "$top": top, "$orderby": "sentDateTime desc",
                        "$select": "id,subject,toRecipients,ccRecipients,sentDateTime,conversationId"})
        return list((out or {}).get("value") or [])

    def event(self, event_id: str) -> dict | None:
        return self.get(f"me/events/{event_id}", {"$select": "id,subject,start,end,attendees,isCancelled"})

    def channel_message(self, team_id: str, channel_id: str, message_id: str) -> dict | None:
        return self.get(f"teams/{team_id}/channels/{channel_id}/messages/{message_id}")

    def chat_message(self, chat_id: str, message_id: str) -> dict | None:
        return self.get(f"chats/{chat_id}/messages/{message_id}")


READERS.update({"calendar": GoogleCalendarReader, "drive": GoogleDriveReader, "docs": GoogleDocsReader,
                "sheets": GoogleSheetsReader, "notion": NotionReader, "linear": LinearReader,
                "outlook": GraphReader, "teams": GraphReader, "onedrive": GraphReader, "sharepoint": GraphReader})
