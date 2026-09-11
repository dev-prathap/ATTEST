import pytest

from attest import Attest, AutoGate, PolicyEngine, SqliteLedger


@pytest.fixture
def ledger():
    return SqliteLedger(":memory:")


@pytest.fixture
def gate():
    return AutoGate("approved", approver="tester")


@pytest.fixture
def client(ledger, gate):
    return Attest(ledger=ledger, gate=gate, policy=PolicyEngine(), agent="test-agent@v1", actor="ram@acme.com")
