"""Entry point 5 — record actions executed elsewhere (n8n, Zapier, a shell script).   python examples/api_only.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from attest import Attest, SqliteLedger  # noqa: E402

at = Attest(ledger=SqliteLedger(":memory:"), agent="zapier-zap-42")
at.attest(system="zapier", verb="send", target="x@ext.com", result={"id": "m1"})                   # acknowledged
at.attest(system="zapier", verb="update", target="deal/777", verified=True, evidence={"dealstage": "won"})  # verified-custom
at.attest(system="zapier", verb="send", target="y@ext.com", verified=False, evidence={"why": "bounced"})  # unverified
for e in at.ledger.entries():
    print(f"#{e.seq} {e.descriptor['system']}.{e.descriptor['verb']} → {e.descriptor['target']}  level={e.verification.level}")
print("chain:", at.ledger.verify_chain().ok)
