import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Attest, ActionPending, ActionRefused, ActionRejected, AutoGate, FileLedger, PendingStore, PolicyEngine, StoreGate,
  canonicalJson, detect, descriptor, shortHash, verifyChain, verify, ConventionDriver, RecipeDriver, GENESIS } from "../src/index.js";
import { entryHash, payloadHash } from "../src/ledger.js";
import { attestedTools } from "../src/adapters/vercel.js";
import { wrapTools as wrapLangchain } from "../src/adapters/langchain.js";
import { wrapTools as wrapMastra } from "../src/adapters/mastra.js";

const fx = JSON.parse(readFileSync(new URL("./fixture-python.json", import.meta.url), "utf8"));

describe("canonical json parity with the Python SDK", () => {
  it("produces byte-identical canonical JSON and hashes", () => {
    expect(canonicalJson(fx.payload)).toBe(fx.canonical);
    expect(shortHash(fx.payload)).toBe(fx.short_hash);
    expect(payloadHash(fx.payload)).toBe(fx.payload_hash);
    expect(entryHash(GENESIS, 1, fx.payload_hash)).toBe(fx.entry_hash);
  });
});

describe("registry", () => {
  it.each([
    [{ toolName: "gmail_send_message" }, "gmail", "send"], [{ toolName: "mcp__slack__post_message" }, "slack", "send"],
    [{ toolName: "hubspot_update_deal" }, "hubspot", "update"], [{ toolName: "stripe_create_refund" }, "stripe", "pay"],
    [{ method: "POST", url: "https://api.someweirdcrm.io/v2/leads" }, "someweirdcrm", "create"],
    [{ method: "PATCH", url: "https://api.hubapi.com/crm/v3/objects/deals/123" }, "hubspot", "update"],
    [{ method: "POST", url: "https://slack.com/api/chat.postMessage" }, "slack", "send"],
    [{ method: "DELETE", url: "https://gmail.googleapis.com/gmail/v1/users/me/messages/18f3abc" }, "gmail", "delete"],
    [{ method: "POST", url: "https://api.stripe.com/v1/charges" }, "stripe", "pay"],
    [{ functionName: "send_email" }, "unknown", "send"], [{ functionName: "frobnicate" }, "unknown", "write"],
  ])("detects %j", (opts, system, verb) => {
    const d = detect(opts as Parameters<typeof detect>[0]);
    expect([d.system, d.verb]).toEqual([system, verb]);
  });
  it("targets and explicit args", () => {
    expect(detect({ toolName: "gmail_send_message" }).target).toBe("message");
    expect(detect({ method: "PATCH", url: "https://api.hubapi.com/crm/v3/objects/deals/123" }).target).toBe("deals/123");
    expect(detect({ system: "google-mail", verb: "send", toolName: "x" }).system).toBe("gmail");
    expect(detect({ toolName: "someweird_frobnicate" }).recognised).toBe(false);
  });
});

describe("policy", () => {
  const e = new PolicyEngine();
  it("classifies recipients and asks on external sends", () => {
    const r = e.evaluate(descriptor({ system: "gmail", verb: "send", params: { to: "arun@newco.com" }, actor: "ram@acme.com" }));
    expect(r.decision).toBe("ask"); expect(r.target_class).toBe("external"); expect(r.rules_fired).toContain("policy:external-send");
    expect(e.evaluate(descriptor({ system: "gmail", verb: "send", params: { to: "bob@acme.com" }, actor: "ram@acme.com" })).target_class).toBe("internal");
  });
  it("holds placeholders, acts on medium, asks on delete/pay, refuses via yaml, resolves groups and agent overrides", () => {
    expect(e.evaluate(descriptor({ verb: "send", params: { body: "Hi [NAME]" } })).hold).toBe(true);
    expect(e.evaluate(descriptor({ system: "hubspot", verb: "update" })).decision).toBe("act");
    expect(e.evaluate(descriptor({ system: "stripe", verb: "pay" })).rules_fired.at(-1)).toBe("policy:destructive-or-money");
    const y = PolicyEngine.fromYaml(`policies:\n  - match: {system: hubspot, verb: delete}\n    decision: refuse\n  - match: {verb: [delete, pay]}\n    decision: ask\n    approvers: [finance]\n  - match: {target_domain: [competitor.com]}\n    decision: refuse\ngroups:\n  finance: [priya@acme.com]\nagents:\n  bot@v1:\n    policies:\n      - match: {system: hubspot, verb: delete}\n        decision: act\n`);
    expect(y.evaluate(descriptor({ system: "gmail", verb: "send", params: { to: "x@competitor.com" } })).decision).toBe("refuse");
    const r = y.evaluate(descriptor({ system: "stripe", verb: "pay" })); expect(r.approver_members).toEqual(["priya@acme.com"]);
    expect(y.evaluate(descriptor({ system: "hubspot", verb: "delete", agent: "bot@v1" })).decision).toBe("act");
    expect(y.evaluate(descriptor({ system: "hubspot", verb: "delete", agent: "other" })).decision).toBe("refuse");
    expect(() => PolicyEngine.fromYaml("policies:\n  - match: {colour: red}\n    decision: act\n")).toThrow(/unknown match keys/);
  });
});

describe("ledger", () => {
  it("chains, verifies, and detects tampering", () => {
    const L = new FileLedger(":memory:");
    const at = new Attest({ ledger: L, gate: new AutoGate(), actor: "ram@acme.com" });
    const rows = [] as unknown[];
    void rows;
    return (async () => {
      const send = at.wrap({ system: "gmail", verb: "send", target: "to" }, async ({ to }: { to: string }) => ({ id: "m1", to }));
      await send({ to: "x@ext.com" }); await send({ to: "y@ext.com" });
      expect(L.count()).toBe(2); expect(L.verifyChain().ok).toBe(true);
      const rowsArr = L.entries(); expect(rowsArr[1].prev_hash).toBe(rowsArr[0].hash);
      const tampered = rowsArr.map(r => ({ ...r })); tampered[0].decision = "act";
      expect(verifyChain(tampered).broken_at).toBe(1);
      expect(JSON.stringify(rowsArr[0].descriptor)).not.toContain("x@ext.com".repeat(0) + '"params"');
      expect(rowsArr[0].params_preview).toEqual({ to: "x@ext.com" });
    })();
  });
});

describe("client", () => {
  it("decides, gates with edits, verifies via custom, records", async () => {
    const L = new FileLedger(":memory:");
    const at = new Attest({ ledger: L, gate: new AutoGate("approved", "ram", { subject: "E" }), actor: "ram@acme.com", agent: "ts-agent" });
    const send = at.wrap({ system: "gmail", verb: "send", target: "to", verify: (r: unknown) => (r as { ok: boolean }).ok }, async ({ to, subject }: { to: string; subject: string }) => ({ id: "m1", ok: subject === "E" }));
    expect(await send({ to: "arun@newco.com", subject: "orig" })).toEqual({ id: "m1", ok: true });
    const e = L.last()!;
    expect(e.confirm.status).toBe("edited"); expect(e.confirm.approver).toBe("ram"); expect(e.verification.level).toBe("verified-custom");
    expect(e.descriptor.target).toBe("arun@newco.com"); expect(e.agent).toBe("ts-agent");
  });
  it("refuses, rejects, records failures, api-only attest", async () => {
    const L = new FileLedger(":memory:");
    const at = new Attest({ ledger: L, gate: new AutoGate("rejected", "bob"), policy: PolicyEngine.fromYaml("policies:\n  - match: {verb: delete}\n    decision: refuse\n  - match: {verb: send}\n    decision: ask\n") });
    await expect(at.wrap({ system: "x", verb: "delete" }, async () => 1)({})).rejects.toBeInstanceOf(ActionRefused);
    await expect(at.wrap({ system: "gmail", verb: "send" }, async () => 1)({ to: "a@b.com" })).rejects.toBeInstanceOf(ActionRejected);
    await expect(at.wrap({ system: "x", verb: "update" }, async () => { throw new Error("vendor down"); })({})).rejects.toThrow("vendor down");
    expect(L.last()!.execution!.status).toBe("failed");
    const rec = await at.attest({ system: "n8n", verb: "send", result: { id: "m1" } }); expect(rec.verification.level).toBe("acknowledged");
    expect((await at.attest({ system: "n8n", verb: "send", verified: false, evidence: { why: "bounced" } })).verification.level).toBe("unverified");
    expect(L.verifyChain().ok).toBe(true);
  });
  it("pending then resume through the store", async () => {
    const store = new PendingStore(":memory:");
    const at = new Attest({ ledger: new FileLedger(":memory:"), gate: new StoreGate(store, { wait: false }) });
    const send = at.wrap({ system: "gmail", verb: "send" }, async ({ to, subject }: { to: string; subject: string }) => ({ id: "m1", subject }));
    let token = "";
    try { await send({ to: "x@ext.com", subject: "orig" }); } catch (e) { token = (e as ActionPending).resumeToken; }
    expect(token).toMatch(/^rsm_/); expect(store.pending()).toHaveLength(1);
    await expect(at.resume(token)).rejects.toBeInstanceOf(ActionPending);
    store.decide(token, { status: "edited", approver: "ram", edits: { subject: "EDITED" }, channel: "cli", decided_at: new Date().toISOString() });
    expect(await send.resume(token)).toEqual({ id: "m1", subject: "EDITED" });
    expect(at.ledger.last()!.confirm.approver).toBe("ram"); expect(at.ledger.count()).toBe(2);
  });
  it("blocks until the store is decided, and expires", async () => {
    const store = new PendingStore(":memory:");
    const at = new Attest({ ledger: new FileLedger(":memory:"), gate: new StoreGate(store, { wait: true, timeoutS: 2, pollMs: 20 }) });
    const send = at.wrap({ system: "gmail", verb: "send" }, async () => ({ id: 1 }));
    setTimeout(() => store.decide(store.pending()[0].id, { status: "approved", approver: "web", channel: "web", decided_at: new Date().toISOString() }), 50);
    expect(await send({ to: "x@ext.com" })).toEqual({ id: 1 });
    const at2 = new Attest({ ledger: new FileLedger(":memory:"), gate: new StoreGate(new PendingStore(":memory:"), { wait: true, timeoutS: 0.1, pollMs: 20 }) });
    await expect(at2.wrap({ system: "gmail", verb: "send" }, async () => 1)({ to: "x@ext.com" })).rejects.toBeInstanceOf(ActionRejected);
  });
});

describe("verification", () => {
  it("ack ladder", async () => {
    const d = descriptor({ system: "x", verb: "create" });
    expect((await verify(d, { id: "1" })).level).toBe("acknowledged");
    expect((await verify(d, { nothing: 1 })).level).toBe("attested-only");
    expect((await verify(d, { issueCreate: { issue: { id: "x" } } })).level).toBe("acknowledged");
    expect((await verify(d, { id: "1" }, { custom: () => { throw new Error("x"); } })).level).toBe("acknowledged");
  });
  it("convention read-back verifies and contradicts", async () => {
    const db: Record<string, unknown> = { "L-1": { id: "L-1", name: "Arun", email: "a@b.com" } };
    const get = async (url: string) => { const k = url.split("/").pop()!; if (!(k in db)) throw new Error("HTTP 404"); return db[k]; };
    const at = new Attest({ ledger: new FileLedger(":memory:"), gate: new AutoGate(), httpGet: get });
    const create = at.wrap({ method: "POST", url: "https://api.someweirdcrm.io/v2/leads" }, async ({ name, email }: { name: string; email: string }) => ({ id: "L-1" }));
    await create({ name: "Arun", email: "a@b.com" });
    let e = at.ledger.last()!; expect(e.verification.level).toBe("verified"); expect(e.verification.method).toBe("read-back:convention");
    const update = at.wrap({ method: "PATCH", url: "https://api.someweirdcrm.io/v2/leads/L-1" }, async () => ({ ok: true }));
    await update({ name: "Changed" });
    e = at.ledger.last()!; expect(e.verification.level).toBe("unverified"); expect((e.verification.evidence.failed as string[])).toEqual(["name"]);
    const drv = new ConventionDriver(get); expect(drv.readUrl(descriptor({ verb: "create", extra: { method: "POST", url: "https://x/v2/leads" } }), { id: 7 })).toBe("https://x/v2/leads/7");
  });
  it("gmail / slack / hubspot recipes over a fake fetch", async () => {
    const fetchImpl = (async (url: string | URL) => {
      const u = String(url);
      const body = u.includes("gmail") ? { id: "m1", labelIds: ["SENT"], payload: { headers: [{ name: "To", value: "Arun <arun@newco.com>" }, { name: "Subject", value: "Hi" }] } }
        : u.includes("slack") ? { ok: true, messages: [{ ts: "1.5", text: "hello" }] }
        : { id: "777", properties: { dealname: "Acme", amount: "10" } };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    const at = new Attest({ ledger: new FileLedger(":memory:"), gate: new AutoGate(), readers: { gmail: "tok", slack: "xoxb", hubspot: "pat" }, fetchImpl });
    await at.wrap({ system: "gmail", verb: "send", target: "to" }, async () => ({ id: "m1" }))({ to: "arun@newco.com", subject: "Hi" });
    expect(at.ledger.last()!.verification.level).toBe("verified");
    await at.wrap({ system: "gmail", verb: "send", target: "to" }, async () => ({ id: "m1" }))({ to: "else@x.com", subject: "Hi" });
    expect(at.ledger.last()!.verification.level).toBe("unverified");
    await at.wrap({ system: "slack", verb: "send" }, async () => ({ ok: true, channel: "C1", ts: "1.5" }))({ channel: "C1", text: "hello" });
    expect(at.ledger.last()!.verification.level).toBe("verified");
    await at.wrap({ system: "hubspot", verb: "update", target: "deal" }, async () => ({ id: "777" }))({ deal_id: "777", properties: { dealname: "Acme", amount: 10 } });
    expect(at.ledger.last()!.verification.level).toBe("verified");
    await at.wrap({ system: "hubspot", verb: "update", target: "deal" }, async () => ({ id: "777" }))({ deal_id: "777", properties: { dealname: "Other" } });
    expect(at.ledger.last()!.verification.level).toBe("unverified");
    expect(new RecipeDriver({}).supports(descriptor({ system: "gmail", verb: "send" }))).toBe(true);
  });
});

describe("adapters", () => {
  it("vercel, langchain.js, mastra tools run through attest", async () => {
    const at = new Attest({ ledger: new FileLedger(":memory:"), gate: new AutoGate("approved", "ram"), actor: "ram@acme.com" });
    const tools = attestedTools(at, { send_email: { description: "send", execute: async (a: { to: string }) => ({ id: "m1", to: a.to }) } }, { send_email: { system: "gmail", verb: "send", target: "to" } });
    expect(await tools.send_email.execute!({ to: "x@ext.com" } as never, {} as never)).toEqual({ id: "m1", to: "x@ext.com" });
    expect(at.ledger.last()!.descriptor.extra).toMatchObject({ framework: "vercel-ai" });
    const [lc] = wrapLangchain(at, [{ name: "update_deal", invoke: async (i: unknown) => ({ id: (i as { deal_id: string }).deal_id }) }], { update_deal: { system: "hubspot", verb: "update", target: "deal_id" } });
    expect(await lc.invoke({ deal_id: "7" })).toEqual({ id: "7" }); expect(at.ledger.last()!.descriptor.target).toBe("7");
    const [ms] = wrapMastra(at, [{ id: "create_lead", execute: async ({ context }) => ({ id: "L-1", ...context }) }], { create_lead: { system: "someweirdcrm", verb: "create" } });
    expect(await ms.execute!({ context: { name: "n" } })).toEqual({ id: "L-1", name: "n" });
    const rej = new Attest({ ledger: new FileLedger(":memory:"), gate: new AutoGate("rejected", "bob") });
    const t2 = attestedTools(rej, { send: { execute: async () => 1 } }, { send: { system: "gmail", verb: "send" } });
    expect(await t2.send.execute!({ to: "x@ext.com" } as never, {} as never)).toMatchObject({ error: expect.stringContaining("rejected") });
  });
});
