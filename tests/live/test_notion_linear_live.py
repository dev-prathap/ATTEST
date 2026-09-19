import uuid

from tests.live.helpers import api, client

NOTION_H = {"Notion-Version": "2022-06-28"}


def test_notion_page_create_and_contradiction(notion_token, notion_parent):
    at = client("notion", notion_token)
    title = f"attest live {uuid.uuid4().hex[:8]}"

    @at.action(system="notion", verb="create", target="page")
    def create(parent, properties):
        return api("POST", "https://api.notion.com/v1/pages", notion_token,
                   {"parent": parent, "properties": properties}, headers=NOTION_H)

    page = create({"page_id": notion_parent},
                  {"title": {"title": [{"text": {"content": title}}]}})
    assert at.ledger.last().verification.level == "verified", at.ledger.last().verification.evidence

    @at.action(system="notion", verb="update", target="page")
    def rename_lost(page_id, properties):
        return {"id": page_id}                     # claimed, never written

    rename_lost(page["id"], {"title": {"title": [{"text": {"content": "never written"}}]}})
    assert at.ledger.last().verification.level == "unverified", at.ledger.last().verification.evidence
    api("PATCH", f"https://api.notion.com/v1/pages/{page['id']}", notion_token, {"archived": True}, headers=NOTION_H)


def test_linear_issue_create_and_contradiction(linear_key):
    at = client("linear", linear_key)
    title = f"attest live {uuid.uuid4().hex[:8]}"
    import os
    team = os.environ.get("ATTEST_LIVE_LINEAR_TEAM") or \
        api("POST", "https://api.linear.app/graphql", linear_key,
            {"query": "{ teams(first: 1) { nodes { id } } }"}, auth="")["data"]["teams"]["nodes"][0]["id"]

    @at.action(system="linear", verb="create", target="issue")
    def create(title, team_id):
        return api("POST", "https://api.linear.app/graphql", linear_key, {
            "query": "mutation($t: String!, $team: String!) { issueCreate(input: {title: $t, teamId: $team}) "
                     "{ success issue { id } } }", "variables": {"t": title, "team": team_id}}, auth="")["data"]

    out = create(title, team)
    assert at.ledger.last().verification.level == "verified", at.ledger.last().verification.evidence
    issue_id = out["issueCreate"]["issue"]["id"]

    @at.action(system="linear", verb="update", target="issue")
    def retitle_lost(issue_id, title):
        return {"issueUpdate": {"success": True}}      # claimed, never written

    retitle_lost(issue_id, "never written")
    assert at.ledger.last().verification.level == "unverified", at.ledger.last().verification.evidence
    api("POST", "https://api.linear.app/graphql", linear_key, {
        "query": "mutation($id: String!) { issueDelete(id: $id) { success } }", "variables": {"id": issue_id}}, auth="")
