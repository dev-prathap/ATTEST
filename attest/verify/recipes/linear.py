"""Linear — issue create / update ⇒ issue(id); project create ⇒ project(id); comment create ⇒ comment(id)."""
from __future__ import annotations

from typing import Any

from attest.descriptor import ActionDescriptor
from attest.verify.match import MatchReport
from attest.verify.readers import LinearReader
from attest.verify.recipes import Recipe, register
from attest.verify.refs import dig, first_id


def _result_id(result: Any, *paths: str) -> str | None:
    for p in paths:
        v = dig(result, p)
        if v:
            return str(v)
    return first_id(result)


def fetch_issue(reader: LinearReader, d: ActionDescriptor, result: Any) -> Any:
    iid = d.params.get("issue_id") or d.params.get("issueId") or d.params.get("id") \
        or _result_id(result, "issue.id", "issueCreate.issue.id", "issueUpdate.issue.id")
    return reader.issue(str(iid)) if iid else None


def compare_issue(d: ActionDescriptor, result: Any, issue: dict) -> MatchReport:
    r = MatchReport(matched=True)
    for k in ("title", "description", "priority"):
        if d.params.get(k) is not None and k in issue:
            r.field_(k, d.params[k], issue.get(k))
    state = d.params.get("state") or d.params.get("state_name") or d.params.get("stateName")
    if state and isinstance(issue.get("state"), dict):
        r.field_("state", state, issue["state"].get("name"))
    assignee = d.params.get("assignee_id") or d.params.get("assigneeId")
    if assignee and isinstance(issue.get("assignee"), dict):
        r.field_("assignee", assignee, issue["assignee"].get("id"))
    team = d.params.get("team_id") or d.params.get("teamId")
    if team and isinstance(issue.get("team"), dict):
        r.field_("team", team, issue["team"].get("id"), team in (issue["team"].get("id"), issue["team"].get("key")))
    if r.compared == 0:
        r.check("issue:exists", bool(issue.get("id")))
    return r


def fetch_project(reader: LinearReader, d: ActionDescriptor, result: Any) -> Any:
    pid = d.params.get("project_id") or _result_id(result, "project.id", "projectCreate.project.id")
    return reader.project(str(pid)) if pid else None


def compare_project(d: ActionDescriptor, result: Any, project: dict) -> MatchReport:
    r = MatchReport(matched=True)
    for k in ("name", "description"):
        if d.params.get(k) is not None and k in project:
            r.field_(k, d.params[k], project.get(k))
    if r.compared == 0:
        r.check("project:exists", bool(project.get("id")))
    return r


def fetch_comment(reader: LinearReader, d: ActionDescriptor, result: Any) -> Any:
    cid = _result_id(result, "comment.id", "commentCreate.comment.id")
    return reader.comment(str(cid)) if cid else None


def compare_comment(d: ActionDescriptor, result: Any, c: dict) -> MatchReport:
    r = MatchReport(matched=True)
    if d.params.get("body") is not None:
        r.field_("body", d.params["body"], c.get("body"))
    iid = d.params.get("issue_id") or d.params.get("issueId")
    if iid and isinstance(c.get("issue"), dict):
        r.field_("issue", iid, c["issue"].get("id"))
    return r


def _t(d: ActionDescriptor, word: str) -> bool:
    return word in (d.target or "").lower() or word in " ".join(d.params.keys()).lower()


register(Recipe("linear.comment", "linear", ("create",), fetch_comment, compare_comment,
                when=lambda d, r: _t(d, "comment")))
register(Recipe("linear.project", "linear", ("create", "update"), fetch_project, compare_project,
                when=lambda d, r: _t(d, "project") and not _t(d, "issue")))
register(Recipe("linear.issue", "linear", ("create", "update", "write"), fetch_issue, compare_issue))
