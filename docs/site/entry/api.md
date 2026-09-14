# API-only — the floor

Anything can at least be recorded. From Python:

```python
attest.attest(system="n8n", verb="send", target="x@ext.com", result={"id": "m1"})           # ⇒ acknowledged
attest.attest(system="n8n", verb="send", verified=True, evidence={"message_id": "m1"})      # ⇒ verified-custom
attest.attest(system="n8n", verb="send", verified=False, evidence={"why": "bounced"})       # ⇒ unverified
```

From anything else, with Attest Cloud:

```bash
curl -X POST $ATTEST_CLOUD_URL/v1/attest -H "Authorization: Bearer $ATTEST_API_KEY" \
  -H "Content-Type: application/json" -d '{"entry": {"action_id": "act_1", "decision": "recorded",
  "risk_tier": "high", "descriptor": {"system": "zapier", "verb": "send", "target": "x@ext.com", "params_hash": "…"},
  "params_hash": "…", "verification": {"level": "acknowledged", "evidence": {"id": "m1"}}}}'
```

`POST /v1/decide` evaluates a descriptor against the org policy for callers that want the decision without the SDK.
