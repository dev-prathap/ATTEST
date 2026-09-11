"""≥ 40 detection patterns across MCP names, URLs, SDK paths, function names, and the unknown app."""
import pytest

from attest.registry import detect, register, risk_for
from attest.registry.systems import registered_domain, system_for_host
from attest.registry.verbs import classify

MCP = [
    ("gmail_send_message", "gmail", "send"),
    ("gmail_create_draft", "gmail", "create"),
    ("gmail_search_messages", "gmail", "search"),
    ("gmail_get_message", "gmail", "get"),
    ("gmail_modify_labels", "gmail", "update"),
    ("google_calendar_create_event", "calendar", "create"),
    ("google_drive_share_file", "drive", "share"),
    ("mcp__slack__post_message", "slack", "send"),
    ("slack_add_reaction", "slack", "update"),
    ("slack-list-channels", "slack", "list"),
    ("hubspot_update_deal", "hubspot", "update"),
    ("hubspot_create_contact", "hubspot", "create"),
    ("notion.pages.create", "notion", "create"),
    ("notion_retrieve_page", "notion", "get"),
    ("linear_create_issue", "linear", "create"),
    ("linearArchiveIssue", "linear", "update"),
    ("microsoft_teams_create_channel_message", "teams", "create"),
    ("outlook_cancel_event", "outlook", "update"),
    ("zoho_crm_convert_lead", "zoho_crm", "update"),
    ("stripe_create_refund", "stripe", "pay"),  # money noun escalates create ⇒ pay
    ("stripe_create_customer", "stripe", "create"),
    ("stripe_charge_customer", "stripe", "pay"),
    ("github_merge_pull_request", "github", "update"),
    ("filesystem_write_file", "filesystem", "write"),
    ("someweird_frobnicate_widget", "unknown", "write"),
    ("deploy_service", "unknown", "execute"),
    ("approve_invoice", "unknown", "approve"),
]


@pytest.mark.parametrize("name,system,verb", MCP)
def test_mcp_tool_names(name, system, verb):
    d = detect(tool_name=name)
    assert (d.system, d.verb) == (system, verb), d


def test_mcp_server_hint_sets_system():
    d = detect(tool_name="send_message", server="slack")
    assert (d.system, d.verb, d.source) == ("slack", "send", "mcp")


def test_mcp_target_is_the_noun():
    assert detect(tool_name="gmail_send_message").target == "message"
    assert detect(tool_name="hubspot_update_deal").target == "deal"


URLS = [
    ("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", "gmail", "send"),
    ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/18f3abc", "gmail", "get"),
    ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=from:x", "gmail", "search"),
    ("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", "calendar", "create"),
    ("DELETE", "https://www.googleapis.com/drive/v3/files/abc123def456", "drive", "delete"),
    ("POST", "https://www.googleapis.com/drive/v3/files/abc123def456/permissions", "drive", "share"),
    ("POST", "https://slack.com/api/chat.postMessage", "slack", "send"),
    ("GET", "https://slack.com/api/conversations.history?channel=C1", "slack", "list"),
    ("PATCH", "https://api.hubapi.com/crm/v3/objects/deals/123", "hubspot", "update"),
    ("POST", "https://api.hubapi.com/crm/v3/objects/contacts", "hubspot", "create"),
    ("GET", "https://api.hubapi.com/crm/v3/objects/contacts/123", "hubspot", "get"),
    ("POST", "https://api.notion.com/v1/pages", "notion", "create"),
    ("POST", "https://api.linear.app/graphql", "linear", "create"),
    ("POST", "https://graph.microsoft.com/v1.0/me/messages/AAMk/send", "outlook", "send"),
    ("POST", "https://graph.microsoft.com/v1.0/teams/t1/channels", "teams", "create"),
    ("POST", "https://api.stripe.com/v1/charges", "stripe", "pay"),
    ("POST", "https://api.stripe.com/v1/refunds", "stripe", "pay"),
    ("POST", "https://api.stripe.com/v1/customers", "stripe", "create"),
    ("GET", "https://api.stripe.com/v1/charges", "stripe", "list"),
    ("DELETE", "https://gmail.googleapis.com/gmail/v1/users/me/messages/18f3abc", "gmail", "delete"),
    ("POST", "https://api.chat.example/v1/rooms/room1234/messages", "chat", "send"),
    ("POST", "https://api.razorpay.com/v1/payouts", "razorpay", "pay"),
    ("PUT", "https://acme.atlassian.net/rest/api/3/issue/PROJ-1", "jira", "update"),
    ("POST", "https://api.someweirdcrm.io/v2/leads", "someweirdcrm", "create"),
    ("GET", "https://api.someweirdcrm.io/v2/leads/L-991", "someweirdcrm", "get"),
    ("DELETE", "https://api.someweirdcrm.io/v2/leads/L-991", "someweirdcrm", "delete"),
    ("POST", "https://internal.acme.co.uk/jobs/run", "acme", "execute"),
    ("POST", "https://api.example.com/v1/documents/abc123def456/share", "example", "share"),
]


@pytest.mark.parametrize("method,url,system,verb", URLS)
def test_url_patterns(method, url, system, verb):
    d = detect(method=method, url=url)
    assert (d.system, d.verb) == (system, verb), d
    assert d.source == "url"


def test_url_target_keeps_resource_and_id():
    assert detect(method="PATCH", url="https://api.hubapi.com/crm/v3/objects/deals/123").target == "deals/123"
    assert detect(method="POST", url="https://api.someweirdcrm.io/v2/leads").target == "leads"


SDK = [
    ("hubspot.crm.deals.update", "hubspot", "update"),
    ("hubspot.crm.contacts.basic_api.create", "hubspot", "create"),
    ("gmail.users().messages().send", "gmail", "send"),
    ("slack_client.chat_postMessage", "slack", "send"),
    ("notion.pages.update", "notion", "update"),
    ("stripe.Transfer.create", "stripe", "pay"),
    ("stripe.Customer.create", "stripe", "create"),
    ("s3.delete_object", "aws", "delete"),
]


@pytest.mark.parametrize("path,system,verb", SDK)
def test_sdk_paths(path, system, verb):
    d = detect(sdk_path=path)
    assert (d.system, d.verb) == (system, verb), d


FUNCS = [
    ("send_email", "send"), ("create_ticket", "create"), ("update_crm_record", "update"), ("delete_user", "delete"),
    ("fetch_report", "get"), ("list_files", "list"), ("charge_card", "pay"), ("run_migration", "execute"),
    ("frobnicate", "write"), ("share_doc_with_client", "share"), ("reply_to_thread", "reply"),
]


@pytest.mark.parametrize("fn,verb", FUNCS)
def test_function_name_heuristics(fn, verb):
    d = detect(function_name=fn)
    assert d.verb == verb and d.system == "unknown" and d.source == "heuristic"


def test_explicit_args_win_and_are_manual():
    d = detect(system="gmail", verb="send", tool_name="something_random")
    assert (d.system, d.verb, d.source, d.recognised) == ("gmail", "send", "manual", True)


def test_explicit_system_alias_is_canonicalised():
    assert detect(system="google-mail", verb="send").system == "gmail"
    assert detect(system="Google Calendar", verb="create").system == "calendar"


def test_customer_override_registry():
    register("acme_internal_tool", system="acme", verb="pay")
    d = detect(tool_name="acme_internal_tool")
    assert (d.system, d.verb, d.source) == ("acme", "pay", "manual")


def test_unknown_write_is_flagged_unrecognised_and_high_risk():
    d = detect(tool_name="someweird_frobnicate_widget")
    assert not d.recognised
    assert risk_for(d.verb, recognised=d.recognised) == "high"


def test_risk_by_verb():
    assert risk_for("search") == "low"
    assert risk_for("update") == "medium"
    assert risk_for("send") == "high"
    assert risk_for("delete") == "very_high"
    assert risk_for("pay") == "very_high"
    assert risk_for("update", action_id="slack_add_reaction") == "low"


def test_classify_strips_batch_prefix():
    assert classify(["batch", "delete", "rows"]) == ("delete", True)
    assert classify(["frobnicate"]) == ("write", False)


def test_registered_domain():
    assert registered_domain("api.someweirdcrm.io") == "someweirdcrm.io"
    assert registered_domain("mail.acme.co.uk") == "acme.co.uk"
    assert registered_domain("localhost") == "localhost"


def test_system_for_host_refines_by_path():
    assert system_for_host("www.googleapis.com", "/drive/v3/files") == "drive"
    assert system_for_host("graph.microsoft.com", "/v1.0/sites/x/lists") == "sharepoint"
    assert system_for_host("api.unknown-vendor.com") == "unknown_vendor"
