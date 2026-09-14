# Decorator

```python
from attest import Attest
at = Attest(agent="followup-agent@v3", actor="ram@acme.com", readers={"gmail": gmail_service})

@at.action(system="gmail", verb="send", target="to", verify=my_check)
def send_email(to, subject, body): ...
```

| argument | meaning |
| --- | --- |
| `system`, `verb` | explicit labels; otherwise inferred from `tool_name=`, `method=`+`url=`, `sdk_path=`, or the function name |
| `target` | a param name (`"to"`), a literal, or a callable over the bound arguments |
| `risk` | override the tier |
| `verify` | your own check `(result)` or `(result, descriptor)`, sync or async ⇒ `verified-custom` / `unverified` |
| `reader`, `readers`, `http_get` | per-action credentials for read-back |
| `params` | reshape what is recorded (drop a blob); never changes what the function receives |

Sync and async functions both work. `with at.run("run-42", actor="alice@acme.com"):` groups actions under one run.
Refusals raise `ActionRefused`; rejections raise `ActionRejected`; pending gates raise `ActionPending(resume_token)`
and `send_email.resume(token)` continues after approval.
