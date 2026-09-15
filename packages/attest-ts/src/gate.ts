/** Gates: console, auto, store (block / pending with a JSON file), cloud. Same decision vocabulary as Python. */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { createInterface } from "node:readline/promises";
import { newId } from "./canonical.js";
import { paramsHash, qualifiedName, type Descriptor } from "./descriptor.js";
import { preview } from "./ledger.js";

export interface ConfirmRequest { id: string; resume_token: string; action_id: string; descriptor: Descriptor; reasons: string[]; risk_tier: string; approvers: string[]; approver_members: string[]; hold: boolean; channel: string; requested_at: string }
export interface ConfirmDecision { status: "approved" | "rejected" | "edited" | "pending" | "expired"; approver?: string | null; edits?: Record<string, unknown> | null; note?: string | null; channel: string; decided_at: string }
export const approved = (d: ConfirmDecision) => d.status === "approved" || d.status === "edited";

export function request(d: Descriptor, reasons: string[], riskTier: string, approvers: string[] = [], hold = false, members: string[] = [], channel = "console"): ConfirmRequest {
  return { id: newId("cfm"), resume_token: newId("rsm"), action_id: d.id, descriptor: d, reasons, risk_tier: riskTier, approvers, approver_members: members, hold, channel, requested_at: new Date().toISOString() };
}
export function requestToDict(r: ConfirmRequest) {
  const d = r.descriptor;
  return { id: r.id, resume_token: r.resume_token, action_id: r.action_id, action: qualifiedName(d), system: d.system, verb: d.verb, target: d.target, target_class: d.target_class, agent: d.agent, actor: d.actor, run_id: d.run_id, params_preview: preview(d.params), params_hash: paramsHash(d), reasons: r.reasons, risk_tier: r.risk_tier, approvers: r.approvers, approver_members: r.approver_members, hold: r.hold, channel: r.channel, requested_at: r.requested_at };
}
export function decisionFromAny(v: unknown, channel = "resume"): ConfirmDecision {
  const now = new Date().toISOString();
  if (v === true || ["approve", "approved", "yes", "y", "ok"].includes(v as string)) return { status: "approved", channel, decided_at: now };
  if (v === false || v == null || ["reject", "rejected", "no", "n"].includes(v as string)) return { status: "rejected", channel, decided_at: now };
  if (typeof v === "object") {
    const o = v as Record<string, unknown>; let status = String(o.status ?? (o.edits ? "edited" : "approved")).toLowerCase();
    status = ({ approve: "approved", reject: "rejected", edit: "edited" } as Record<string, string>)[status] ?? status;
    if (status === "approved" && o.edits) status = "edited";
    return { status: status as ConfirmDecision["status"], approver: o.approver as string | undefined, edits: (o.edits as Record<string, unknown>) ?? null, note: o.note as string | undefined, channel: (o.channel as string) ?? channel, decided_at: now };
  }
  return { status: "rejected", note: `unparseable decision ${JSON.stringify(v)}`, channel, decided_at: now };
}

export interface Gate { name: string; confirm(r: ConfirmRequest): Promise<ConfirmDecision> }

export class AutoGate implements Gate {
  name = "auto"; requests: ConfirmRequest[] = [];
  constructor(private decision: "approved" | "rejected" = "approved", private approver = "auto", private edits?: Record<string, unknown>) {}
  async confirm(r: ConfirmRequest): Promise<ConfirmDecision> {
    this.requests.push(r);
    return { status: this.decision === "approved" && this.edits ? "edited" : this.decision, approver: this.approver, edits: this.edits ?? null, channel: this.name, decided_at: new Date().toISOString() };
  }
}

export class ConsoleGate implements Gate {
  name = "console";
  constructor(private input: NodeJS.ReadableStream = process.stdin, private output: NodeJS.WritableStream = process.stdout, private approver?: string) {}
  async confirm(r: ConfirmRequest): Promise<ConfirmDecision> {
    const who = this.approver ?? process.env.USER ?? "console";
    if (!(this.input as NodeJS.ReadStream).isTTY && !(this.input as { _attestForceInteractive?: boolean })._attestForceInteractive)
      return { status: "rejected", approver: who, note: "non-interactive stdin: rejected by default", channel: this.name, decided_at: new Date().toISOString() };
    const d = r.descriptor;
    this.output.write(`\n┌─ attest: confirmation required\n│ action   ${qualifiedName(d)}   risk=${r.risk_tier}   target=${d.target_class}\n│ params   ${JSON.stringify(preview(d.params))}\n` + r.reasons.map(x => `│ why      ${x}\n`).join("") + `└─ [y] approve   [n] reject   [e] edit params as JSON\n`);
    const rl = createInterface({ input: this.input, output: this.output });
    try {
      for (;;) {
        const ans = (await rl.question("attest> ")).trim().toLowerCase();
        if (["y", "yes"].includes(ans)) return { status: "approved", approver: who, channel: this.name, decided_at: new Date().toISOString() };
        if (["n", "no", ""].includes(ans)) return { status: "rejected", approver: who, channel: this.name, decided_at: new Date().toISOString() };
        if (["e", "edit"].includes(ans)) {
          try { const edits = JSON.parse(await rl.question("new params (JSON): ")); if (edits && typeof edits === "object") return { status: "edited", approver: who, edits, channel: this.name, decided_at: new Date().toISOString() }; } catch { this.output.write("  invalid JSON; try again\n"); }
        }
      }
    } finally { rl.close(); }
  }
}

/** Pending store on a JSON file (or memory): the analogue of Python's PendingStore. */
export interface StoreRow { id: string; resume_token: string; action_id: string; status: string; channel?: string | null; descriptor: Descriptor; reasons: string[]; risk_tier: string; approvers: string[]; approver_members: string[]; hold: boolean; approver?: string | null; edits?: Record<string, unknown> | null; note?: string | null; requested_at: string; decided_at?: string | null; expires_at?: string | null }
export class PendingStore {
  private rows: StoreRow[] = [];
  constructor(public path = ".attest/pending.json") { if (path !== ":memory:" && existsSync(path)) this.rows = JSON.parse(readFileSync(path, "utf8")); }
  private save() { if (this.path !== ":memory:") { mkdirSync(dirname(this.path), { recursive: true }); writeFileSync(this.path, JSON.stringify(this.rows)); } }
  private reload() { if (this.path !== ":memory:" && existsSync(this.path)) this.rows = JSON.parse(readFileSync(this.path, "utf8")); }
  create(r: ConfirmRequest, ttlS?: number | null): string {
    this.reload();
    this.rows.push({ id: r.id, resume_token: r.resume_token, action_id: r.action_id, status: "pending", channel: r.channel, descriptor: r.descriptor, reasons: r.reasons, risk_tier: r.risk_tier, approvers: r.approvers, approver_members: r.approver_members, hold: r.hold, requested_at: r.requested_at, expires_at: ttlS ? new Date(Date.now() + ttlS * 1000).toISOString() : null });
    this.save(); return r.resume_token;
  }
  private expire() { const now = Date.now(); for (const r of this.rows) if (r.status === "pending" && r.expires_at && Date.parse(r.expires_at) < now) { r.status = "expired"; r.decided_at = new Date().toISOString(); } }
  get(ref: string): StoreRow | null { this.reload(); this.expire(); return this.rows.find(r => r.id === ref || r.resume_token === ref) ?? null; }
  pending(): StoreRow[] { this.reload(); this.expire(); return this.rows.filter(r => r.status === "pending"); }
  decide(ref: string, d: ConfirmDecision): boolean {
    this.reload(); const r = this.rows.find(x => (x.id === ref || x.resume_token === ref) && x.status === "pending"); if (!r) return false;
    Object.assign(r, { status: d.status, approver: d.approver ?? null, edits: d.edits ?? null, note: d.note ?? null, decided_at: d.decided_at, channel: d.channel ?? r.channel }); this.save(); return true;
  }
  decision(ref: string): ConfirmDecision | null {
    const r = this.get(ref); if (!r) return null;
    if (r.status === "pending") return { status: "pending", channel: r.channel ?? "store", decided_at: new Date().toISOString() };
    return { status: r.status as ConfirmDecision["status"], approver: r.approver, edits: r.edits, note: r.note, channel: r.channel ?? "store", decided_at: r.decided_at ?? new Date().toISOString() };
  }
  request(ref: string): ConfirmRequest | null {
    const r = this.get(ref); if (!r) return null;
    return { id: r.id, resume_token: r.resume_token, action_id: r.action_id, descriptor: r.descriptor, reasons: r.reasons, risk_tier: r.risk_tier, approvers: r.approvers, approver_members: r.approver_members, hold: r.hold, channel: r.channel ?? "store", requested_at: r.requested_at };
  }
  async wait(ref: string, timeoutS: number | null, pollMs = 500): Promise<ConfirmDecision> {
    const deadline = timeoutS ? Date.now() + timeoutS * 1000 : null;
    for (;;) {
      const d = this.decision(ref); if (!d) return { status: "rejected", note: "unknown request", channel: "store", decided_at: new Date().toISOString() };
      if (d.status !== "pending") return d;
      if (deadline && Date.now() >= deadline) { this.decide(ref, { status: "expired", note: `no decision within ${timeoutS}s`, channel: "store", decided_at: new Date().toISOString() }); return this.decision(ref)!; }
      await new Promise(r => setTimeout(r, pollMs));
    }
  }
}

export interface Notifier { name: string; notify(r: ConfirmRequest, store: PendingStore): Promise<void> | void }

export class StoreGate implements Gate {
  name = "store";
  constructor(public store = new PendingStore(), private opts: { notifiers?: Notifier[]; wait?: boolean; timeoutS?: number | null; pollMs?: number; ttlS?: number | null } = {}) {
    if (opts.notifiers?.length) this.name = opts.notifiers.map(n => n.name).join("+");
  }
  async confirm(r: ConfirmRequest): Promise<ConfirmDecision> {
    r.channel = this.name; this.store.create(r, this.opts.ttlS ?? 86400);
    for (const n of this.opts.notifiers ?? []) { try { await n.notify(r, this.store); } catch (e) { console.warn(`attest: notifier ${n.name} failed: ${(e as Error).message}`); } }
    if (this.opts.wait === false) return { status: "pending", channel: this.name, decided_at: new Date().toISOString() };
    return this.store.wait(r.id, this.opts.timeoutS ?? 900, this.opts.pollMs ?? 500);
  }
}

/** Signed webhook POST of the request to the customer's endpoint (same HMAC scheme as Python: v1=hmac(secret, ts + "." + body)). */
export class WebhookNotifier implements Notifier {
  name = "webhook";
  constructor(private url: string, private opts: { secret?: string; confirmUrl?: string; fetchImpl?: typeof fetch } = {}) {}
  async notify(r: ConfirmRequest) {
    const { createHmac } = await import("node:crypto");
    const body = JSON.stringify({ type: "attest.confirm_request", ...requestToDict(r), ...(this.opts.confirmUrl ? { confirm_url: `${this.opts.confirmUrl.replace(/\/$/, "")}/confirm/${r.id}` } : {}) });
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.opts.secret) { const ts = String(Math.floor(Date.now() / 1000)); headers["X-Attest-Timestamp"] = ts; headers["X-Attest-Signature"] = "v1=" + createHmac("sha256", this.opts.secret).update(`${ts}.${body}`).digest("hex"); }
    await (this.opts.fetchImpl ?? fetch)(this.url, { method: "POST", headers, body });
  }
}
