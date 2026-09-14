"""Live read-back tests against real accounts. Every test is skipped unless its credentials are set.

    ATTEST_LIVE_GMAIL_TOKEN     OAuth access token with gmail.send + gmail.readonly (or gmail.modify)
    ATTEST_LIVE_GMAIL_TO        recipient for the test send (defaults to the token's own address via 'me')
    ATTEST_LIVE_SLACK_TOKEN     bot token (xoxb-…) with chat:write, channels:history, channels:read
    ATTEST_LIVE_SLACK_CHANNEL   channel id the bot is in
    ATTEST_LIVE_HUBSPOT_TOKEN   private-app token with crm.objects.contacts read/write

Run:  ATTEST_LIVE_GMAIL_TOKEN=… pytest tests/live -q
"""
import os

import pytest


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        pytest.skip(f"{name} not set")
    return v


@pytest.fixture
def gmail_token():
    return env("ATTEST_LIVE_GMAIL_TOKEN")


@pytest.fixture
def slack_token():
    return env("ATTEST_LIVE_SLACK_TOKEN")


@pytest.fixture
def slack_channel():
    return env("ATTEST_LIVE_SLACK_CHANNEL")


@pytest.fixture
def hubspot_token():
    return env("ATTEST_LIVE_HUBSPOT_TOKEN")
