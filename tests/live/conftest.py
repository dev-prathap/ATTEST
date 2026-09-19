"""Live read-back tests against real accounts. Every test skips unless its credentials are set.

    ATTEST_LIVE_GMAIL_TOKEN     OAuth access token with gmail.send + gmail.readonly (or gmail.modify)
    ATTEST_LIVE_GMAIL_TO        recipient for the test send (default: the token's own mailbox)
    ATTEST_LIVE_SLACK_TOKEN     bot token (xoxb-…) with chat:write, channels:history, channels:read
    ATTEST_LIVE_SLACK_CHANNEL   channel id the bot is a member of
    ATTEST_LIVE_HUBSPOT_TOKEN   private-app token with crm.objects.contacts read/write
    ATTEST_LIVE_NOTION_TOKEN    integration token;  ATTEST_LIVE_NOTION_PARENT  a page id it can write to
    ATTEST_LIVE_LINEAR_KEY      API key;            ATTEST_LIVE_LINEAR_TEAM    team id (optional, else the first)

    pytest tests/live -q                    # only what you have credentials for
    pytest tests/live -q --live-report      # plus a ledger table you can paste into a launch post

Every test writes to the real account: an email to yourself, a message in the test channel, a contact that is
deleted again. Use a sandbox workspace.
"""
from __future__ import annotations

import os

import pytest

from tests.live.helpers import LEDGER, api


def pytest_addoption(parser):
    parser.addoption("--live-report", action="store_true", help="print the ledger after live tests")


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        pytest.skip(f"{name} not set")
    return v




# ── credentials, each validated once so a bad token fails loudly instead of oddly ──────────────
@pytest.fixture(scope="session")
def gmail_token():
    tok = env("ATTEST_LIVE_GMAIL_TOKEN")
    api("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", tok)
    return tok


@pytest.fixture(scope="session")
def gmail_to(gmail_token):
    return os.environ.get("ATTEST_LIVE_GMAIL_TO") or \
        api("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", gmail_token)["emailAddress"]


@pytest.fixture(scope="session")
def slack_token():
    tok = env("ATTEST_LIVE_SLACK_TOKEN")
    out = api("POST", "https://slack.com/api/auth.test", tok, {})
    if not out.get("ok"):
        pytest.fail(f"slack auth.test: {out.get('error')}", pytrace=False)
    return tok


@pytest.fixture(scope="session")
def slack_channel():
    return env("ATTEST_LIVE_SLACK_CHANNEL")


@pytest.fixture(scope="session")
def hubspot_token():
    tok = env("ATTEST_LIVE_HUBSPOT_TOKEN")
    api("GET", "https://api.hubapi.com/crm/v3/objects/contacts?limit=1", tok)
    return tok


@pytest.fixture(scope="session")
def notion_token():
    tok = env("ATTEST_LIVE_NOTION_TOKEN")
    api("GET", "https://api.notion.com/v1/users/me", tok, headers={"Notion-Version": "2022-06-28"})
    return tok


@pytest.fixture(scope="session")
def notion_parent():
    return env("ATTEST_LIVE_NOTION_PARENT")


@pytest.fixture(scope="session")
def linear_key():
    key = env("ATTEST_LIVE_LINEAR_KEY")
    out = api("POST", "https://api.linear.app/graphql", key, {"query": "{ viewer { id } }"}, auth="")
    if out.get("errors"):
        pytest.fail(f"linear: {out['errors'][0].get('message')}", pytrace=False)
    return key


# ── report ─────────────────────────────────────────────────────────────────────────────────────
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("--live-report") or not LEDGER.count():
        return
    w = terminalreporter
    w.write_sep("=", "attest live ledger")
    for e in LEDGER.entries():
        d = e.descriptor
        w.write_line(f"#{e.seq} {d['system']}.{d['verb']:<7} → {str(d.get('target'))[:38]:<38} "
                     f"{e.decision:<7} {e.confirm.status:<9} {e.verification.level:<16} {e.verification.method or '-'}")
        failed = e.verification.evidence.get("failed")
        if failed:
            w.write_line(f"    failed fields: {failed}")
    rep = LEDGER.verify_chain()
    w.write_line(f"chain: ok={rep.ok} entries={rep.checked}")
