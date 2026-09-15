/** Attest Cloud client + a ledger that pushes with an outbox + a cloud-backed pending store (mirrors attest/cloud.py). */
import type { ConfirmDecision, ConfirmRequest } from "./gate.js";
import { FileLedger, type LedgerEntry } from "./ledger.js";
import { loadDoc, PolicyEngine, type PolicyContext } from "./policy.js";

export class CloudError extends Error { constructor(public status: number, public detail: unknown) { super(`cloud ${status}: ${JSON.stringify(detail)}`); } }

export class CloudClient {
  url: string; apiKey: string;
  constructor(url?: string, apiKey?: string, private fetchImpl: typeof fetch = fetch) {
    this.url = (url ?? process.env.ATTEST_CLOUD_URL ?? "").replace(/\/$/, ""); this.apiKey = apiKey ?? process.env.ATTEST_API_KEY ?? "";
    if (!this.url || !this.apiKey) throw new Error("Attest Cloud needs url + apiKey (or ATTEST_CLOUD_URL / ATTEST_API_KEY)");
  }
  async request<T = unknown>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
    let url = this.url + path;
    if (params) url += "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString();
    const res = await this.fetchImpl(url, { method, headers: { Authorization: `Bearer ${this.apiKey}`, Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) }, body: body !== undefined ? JSON.stringify(body) : undefined });
    const text = await res.text(); let out: unknown = null; try { out = text ? JSON.parse(text) : null; } catch { out = text; }
    if (res.status >= 400) throw new CloudError(res.status, (out as { detail?: unknown })?.detail ?? out);
    return out as T;
  }
  me() { return this.request("GET", "/v1/me"); }
  attest(entries: unknown[]) { return this.request<{ id: string; seq: number; hash: string }[]>("POST", "/v1/attest", { entries }); }
  policy() { return this.request<{ version: number; yaml: string }>("GET", "/v1/policy"); }
}

export class CloudLedger extends FileLedger {
  outbox: LedgerEntry[] = []; lastPush: unknown = null;
  constructor(public cloud: CloudClient, path = ".attest/ledger.jsonl", public sync = true) { super(path); }
  append(e: LedgerEntry): LedgerEntry { const row = super.append(e); this.outbox.push(row); if (this.sync) void this.flush(); return row; }
  async flush(batch = 100): Promise<number> {
    if (!this.outbox.length) return 0;
    const rows = this.outbox.slice(0, batch);
    try { this.lastPush = await this.cloud.attest(rows); } catch (e) { console.warn(`attest cloud sink unavailable (${(e as Error).message}); ${this.outbox.length} entries queued`); return 0; }
    this.outbox.splice(0, rows.length); return rows.length;
  }
}

export async function cloudPolicy(cloud: CloudClient, ctx?: PolicyContext, fallback?: PolicyEngine): Promise<PolicyEngine> {
  try { const p = await cloud.policy(); const e = new PolicyEngine(loadDoc(p.yaml), ctx); (e as { cloudVersion?: number }).cloudVersion = p.version; return e; }
  catch (e) { console.warn(`attest cloud policy unavailable (${(e as Error).message}); using local policy`); return fallback ?? new PolicyEngine(null, ctx); }
}

/** PendingStore-compatible view over the cloud confirm API. */
export class CloudStore {
  path = ":cloud:";
  constructor(private cloud: CloudClient) {}
  async create(r: ConfirmRequest, ttlS: number | null = 86400) {
    await this.cloud.request("POST", "/v1/confirm", { id: r.id, resume_token: r.resume_token, action_id: r.action_id, descriptor: { ...r.descriptor, result: undefined }, reasons: r.reasons, risk_tier: r.risk_tier, approvers: r.approvers, approver_members: r.approver_members, hold: r.hold, ttl_s: ttlS });
    return r.resume_token;
  }
  async get(ref: string): Promise<Record<string, unknown> | null> { try { return await this.cloud.request("GET", `/v1/confirm/${ref}`); } catch (e) { if (e instanceof CloudError && e.status === 404) return null; throw e; } }
  async decision(ref: string): Promise<ConfirmDecision | null> {
    const row = await this.get(ref); if (!row) return null;
    if (row.status === "pending") return { status: "pending", channel: (row.channel as string) ?? "cloud", decided_at: new Date().toISOString() };
    return { status: row.status as ConfirmDecision["status"], approver: row.approver as string, edits: row.edits as Record<string, unknown> | null, note: row.note as string, channel: (row.channel as string) ?? "cloud", decided_at: (row.decided_at as string) ?? new Date().toISOString() };
  }
  async wait(ref: string, timeoutS: number | null, pollMs = 2000): Promise<ConfirmDecision> {
    const deadline = timeoutS ? Date.now() + timeoutS * 1000 : null;
    for (;;) {
      let d: ConfirmDecision | null; try { d = await this.decision(ref); } catch { d = { status: "pending", channel: "cloud", decided_at: new Date().toISOString() }; }
      if (!d) return { status: "rejected", note: "unknown request", channel: "cloud", decided_at: new Date().toISOString() };
      if (d.status !== "pending") return d;
      if (deadline && Date.now() >= deadline) return { status: "expired", note: `no decision within ${timeoutS}s`, channel: "cloud", decided_at: new Date().toISOString() };
      await new Promise(r => setTimeout(r, pollMs));
    }
  }
}
