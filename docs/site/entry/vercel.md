# Vercel AI SDK — via the HTTP API

**Prefer the [TypeScript SDK](typescript.md)** (`@attestlayer/sdk/adapters/vercel`). The HTTP-API approach below works from any runtime without the SDK; wrap tools with two calls to Attest Cloud: `POST /v1/decide`
before the tool runs and `POST /v1/attest` after. Confirmations use `POST /v1/confirm` + polling.

```ts
import { tool } from "ai";
import { z } from "zod";

const CLOUD = process.env.ATTEST_CLOUD_URL!, KEY = process.env.ATTEST_API_KEY!;
const H = { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" };
const hash = async (o: unknown) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",
  new TextEncoder().encode(JSON.stringify(o, Object.keys(o as object).sort()))))).map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 16);

export function attested<T extends Record<string, unknown>>(name: string, meta: { system: string; verb: string; target?: keyof T },
  t: ReturnType<typeof tool>) {
  const run = t.execute!;
  return { ...t, execute: async (args: T, opts: unknown) => {
    const descriptor = { system: meta.system, verb: meta.verb, target: meta.target ? String(args[meta.target]) : undefined,
      params: args, agent: "vercel-agent@v1" };
    const decision = await fetch(`${CLOUD}/v1/decide`, { method: "POST", headers: H, body: JSON.stringify({ descriptor }) }).then(r => r.json());
    if (decision.decision === "refuse") return { error: `attest refused: ${decision.reasons.join("; ")}` };
    let confirm = { status: "not_required" } as Record<string, unknown>;
    if (decision.decision === "ask") {
      const req = await fetch(`${CLOUD}/v1/confirm`, { method: "POST", headers: H, body: JSON.stringify({
        action_id: crypto.randomUUID(), descriptor, reasons: decision.reasons, risk_tier: decision.risk_tier,
        approvers: decision.approvers }) }).then(r => r.json());
      for (;;) {                                    // block until a human decides (or return req.resume_token to resume later)
        const row = await fetch(`${CLOUD}/v1/confirm/${req.id}`, { headers: H }).then(r => r.json());
        if (row.status !== "pending") { confirm = row; break; }
        await new Promise(r => setTimeout(r, 2000));
      }
      if (confirm.status === "rejected" || confirm.status === "expired") return { error: "attest: rejected by a human" };
      if (confirm.edits) args = { ...args, ...(confirm.edits as Partial<T>) };
    }
    const result = await run(args, opts as never);
    await fetch(`${CLOUD}/v1/attest`, { method: "POST", headers: H, body: JSON.stringify({ entry: {
      action_id: crypto.randomUUID(), decision: decision.decision, risk_tier: decision.risk_tier, reasons: decision.reasons,
      descriptor: { ...descriptor, params: undefined, params_hash: await hash(args) }, params_hash: await hash(args),
      confirm: { status: confirm.status, approver: confirm.approver, channel: confirm.channel },
      execution: { status: "done", result_hash: await hash(result) },
      verification: { level: (result as { id?: unknown })?.id ? "acknowledged" : "attested-only", evidence: {} } } }) });
    return result;
  } };
}
```

Read-back (`verified`) needs the recipes, which live in the Python SDK today; a TypeScript port of the
registry and recipes is Phase 3 (P3.2).
