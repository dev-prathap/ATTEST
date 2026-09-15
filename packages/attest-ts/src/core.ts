/** The Attest client: decide → gate → execute → verify → attest. `wrap()` returns an attested async function. */
import { shortHash } from "./canonical.js";
import { descriptor, paramsHash, type Descriptor, type RiskTier, type Verb } from "./descriptor.js";
import { AutoGate, ConsoleGate, StoreGate, approved, request, type ConfirmDecision, type Gate } from "./gate.js";
import { CloudClient, CloudLedger, CloudStore, cloudPolicy } from "./cloud.js";
import { entryFromDescriptor, FileLedger, preview, type Ledger, type LedgerEntry } from "./ledger.js";
import { PolicyEngine, type PolicyContext, type PolicyResult } from "./policy.js";
import { detect, type Detection } from "./registry.js";
import { ConventionDriver, RecipeDriver, verify, type Custom, type HttpGet, type ReadBackDriver } from "./verify.js";

export class ActionRefused extends Error { constructor(public actionId: string, public reasons: string[]) { super(`refused: ${reasons.join("; ")}`); } }
export class ActionRejected extends Error { constructor(public actionId: string, public approver?: string | null, public note?: string | null) { super(`rejected by ${approver ?? "approver"}${note ? `: ${note}` : ""}`); } }
export class ActionPending extends Error { constructor(public actionId: string, public resumeToken: string) { super(`pending confirmation; resume_token=${resumeToken}`); } }

export interface ActionSpec { system?: string; verb?: Verb; target?: string | ((args: Record<string, unknown>) => string | null | undefined); risk?: RiskTier; verify?: Custom; toolName?: string; method?: string; url?: string; name?: string; readers?: Record<string, string | HttpGet>; httpGet?: HttpGet; params?: (args: Record<string, unknown>) => Record<string, unknown> }
export interface Receipt<T = unknown> { entry: LedgerEntry; result: T; descriptor: Descriptor; policy: PolicyResult; confirm: ConfirmDecision | null }
export interface AttestOptions { ledger?: Ledger; policy?: PolicyEngine; gate?: Gate; agent?: string; actor?: string; readers?: Record<string, string | HttpGet>; httpGet?: HttpGet; drivers?: ReadBackDriver[]; store?: { get(ref: string): unknown; decision(ref: string): Promise<ConfirmDecision | null> | ConfirmDecision | null; request?(ref: string): unknown; create?(r: unknown): unknown }; fetchImpl?: typeof fetch }

export class Attest {
  ledger: Ledger; policy: PolicyEngine; gate: Gate; agent?: string; actor?: string; readers: Record<string, string | HttpGet>; httpGet?: HttpGet; drivers: ReadBackDriver[];
  store: AttestOptions["store"]; private resumables = new Map<string, { execute: (p: Record<string, unknown>) => Promise<unknown>; spec: ActionSpec; d: Descriptor }>();
  private runId: string | null = null; private fetchImpl: typeof fetch;

  constructor(opts: AttestOptions = {}) {
    this.ledger = opts.ledger ?? new FileLedger(process.env.ATTEST_LEDGER ?? ".attest/ledger.jsonl");
    this.policy = opts.policy ?? new PolicyEngine();
    this.gate = opts.gate ?? (process.env.ATTEST_AUTO_APPROVE != null ? new AutoGate(["1", "true", "yes"].includes(process.env.ATTEST_AUTO_APPROVE.toLowerCase()) ? "approved" : "rejected", "env") : new ConsoleGate());
    this.agent = opts.agent ?? process.env.ATTEST_AGENT; this.actor = opts.actor ?? process.env.ATTEST_ACTOR;
    this.readers = opts.readers ?? {}; this.httpGet = opts.httpGet; this.drivers = opts.drivers ?? []; this.fetchImpl = opts.fetchImpl ?? fetch;
    this.store = opts.store ?? (this.gate instanceof StoreGate ? this.gate.store : undefined);
  }

  /** Cloud-wired client: synced ledger, cloud policy, cloud-routed confirmations. */
  static async cloud(opts: { url?: string; apiKey?: string; wait?: boolean; timeoutS?: number; pollMs?: number; ledgerPath?: string; fetchImpl?: typeof fetch } & Omit<AttestOptions, "ledger" | "policy" | "gate" | "store"> = {}): Promise<Attest> {
    const cloud = new CloudClient(opts.url, opts.apiKey, opts.fetchImpl);
    const ledger = new CloudLedger(cloud, opts.ledgerPath ?? process.env.ATTEST_LEDGER ?? ".attest/ledger.jsonl");
    const store = new CloudStore(cloud);
    const gate: Gate = { name: "cloud", confirm: async r => { r.channel = "cloud"; await store.create(r); return opts.wait === false ? { status: "pending", channel: "cloud", decided_at: new Date().toISOString() } : store.wait(r.id, opts.timeoutS ?? 900, opts.pollMs ?? 2000); } };
    const policy = await cloudPolicy(cloud, {});
    const at = new Attest({ ...opts, ledger, policy, gate, store: store as unknown as AttestOptions["store"] });
    (at as { cloud?: CloudClient }).cloud = cloud; return at;
  }

  async run<T>(runId: string | null, fn: () => Promise<T>): Promise<T> { const prev = this.runId; this.runId = runId ?? `run_${shortHash(Date.now())}`; try { return await fn(); } finally { this.runId = prev; } }

  private driversFor(spec: ActionSpec): ReadBackDriver[] {
    const out = [...this.drivers];
    const readers = { ...this.readers, ...(spec.readers ?? {}) }; if (Object.keys(readers).length) out.push(new RecipeDriver(readers, this.fetchImpl));
    const get = spec.httpGet ?? this.httpGet; if (get) out.push(new ConventionDriver(get));
    return out;
  }

  /** Wrap a function: `const send = at.wrap({system: "gmail", verb: "send", target: "to"}, async ({to, subject}) => …)`. */
  wrap<A extends Record<string, unknown>, R>(spec: ActionSpec, fn: (args: A) => Promise<R> | R): ((args: A) => Promise<R>) & { resume: (token: string) => Promise<R> } {
    const wrapped = async (args: A): Promise<R> => {
      const det = detect({ system: spec.system, verb: spec.verb, toolName: spec.toolName, method: spec.method, url: spec.url, functionName: spec.name ?? fn.name });
      const d = this.describe(det, spec, args as Record<string, unknown>);
      const receipt = await this.runAction<R>(d, p => fn({ ...args, ...only(args, p) } as A), det.recognised, spec);
      return receipt.result;
    };
    return Object.assign(wrapped, { resume: async (token: string) => (await this.resume<R>(token)).result });
  }

  describe(det: Detection, spec: ActionSpec, args: Record<string, unknown>): Descriptor {
    const recorded = spec.params ? spec.params(args) : args;
    const target = typeof spec.target === "function" ? spec.target(args) : typeof spec.target === "string" && spec.target in args ? String(args[spec.target]) : spec.target ?? det.target;
    return descriptor({ system: det.system, verb: det.verb, target: target ?? null, params: jsonable(recorded) as Record<string, unknown>, actor: this.actor ?? null, agent: this.agent ?? null, run_id: this.runId, risk: spec.risk ?? null, source: det.source, extra: Object.fromEntries(Object.entries({ method: spec.method, url: spec.url, tool_name: spec.toolName }).filter(([, v]) => v)) });
  }

  async runAction<T>(d: Descriptor, execute: (p: Record<string, unknown>) => Promise<T> | T, recognised = true, spec: ActionSpec = {}): Promise<Receipt<T>> {
    const pol = this.policy.evaluate(d, recognised); d.target_class = pol.target_class;
    let entry = entryFromDescriptor(d, pol.decision, pol.risk_tier, { reasons: pol.reasons, rules_fired: pol.rules_fired, target_class: pol.target_class });
    if (pol.decision === "refuse") { this.ledger.append(entry); throw new ActionRefused(d.id, pol.reasons); }
    let decision: ConfirmDecision | null = null;
    if (pol.decision === "ask") {
      const req = request(d, pol.reasons, pol.risk_tier, pol.approvers, pol.hold, pol.approver_members, this.gate.name);
      decision = await this.gate.confirm(req);
      if (decision.status === "pending") {
        entry.confirm = { status: "pending", channel: decision.channel, requested_at: req.requested_at }; this.ledger.append(entry);
        this.resumables.set(req.resume_token, { execute: async p => execute(p), spec, d }); throw new ActionPending(d.id, req.resume_token);
      }
      [d, entry] = this.afterConfirm(d, entry, decision, req.requested_at);
    }
    return this.finish<T>(d, entry, execute, spec, pol, decision);
  }

  private afterConfirm(d: Descriptor, entry: LedgerEntry, dec: ConfirmDecision, requestedAt: string): [Descriptor, LedgerEntry] {
    entry.confirm = { status: dec.status, channel: dec.channel, approver: dec.approver ?? null, requested_at: requestedAt, decided_at: dec.decided_at, edits: dec.edits ?? null, note: dec.note ?? null };
    if (!approved(dec)) { this.ledger.append(entry); throw new ActionRejected(d.id, dec.approver, dec.note ?? dec.status); }
    if (dec.edits) { d = { ...d, params: { ...d.params, ...(jsonable(dec.edits) as Record<string, unknown>) } }; entry.descriptor = { ...entry.descriptor, params_hash: paramsHash(d) }; entry.params_hash = paramsHash(d); entry.params_preview = preview(d.params); }
    return [d, entry];
  }

  private async finish<T>(d: Descriptor, entry: LedgerEntry, execute: (p: Record<string, unknown>) => Promise<T> | T, spec: ActionSpec, pol: PolicyResult, decision: ConfirmDecision | null): Promise<Receipt<T>> {
    const t0 = Date.now(); let result: T | undefined; let err: unknown;
    try { result = await execute(d.params); } catch (e) { err = e; }
    if (err) {
      entry.execution = { status: "failed", error: `${(err as Error).name}: ${(err as Error).message}`.slice(0, 400), duration_ms: Date.now() - t0 };
      entry.verification = { level: "attested-only", method: "none", evidence: { detail: "execution failed" } }; this.ledger.append(entry); throw err;
    }
    entry.execution = { status: "done", result_hash: result == null ? null : shortHash(jsonable(result)), result_preview: preview(result), duration_ms: Date.now() - t0 };
    entry.verification = await verify({ ...d, result }, result, { custom: spec.verify, drivers: this.driversFor(spec) });
    const stored = this.ledger.append(entry);
    return { entry: stored, result: result as T, descriptor: d, policy: pol, confirm: decision };
  }

  /** Continue a parked action after a human decided (same process, or pass `execute`). */
  async resume<T>(token: string, execute?: (p: Record<string, unknown>) => Promise<T> | T): Promise<Receipt<T>> {
    if (!this.store) throw new Error("resume needs a store-backed gate");
    const dec = await this.store.decision(token); if (!dec) throw new Error(`unknown resume token ${token}`);
    if (dec.status === "pending") { const saved = this.resumables.get(token); throw new ActionPending(saved?.d.id ?? "", token); }
    const saved = this.resumables.get(token); const req = (this.store.request?.(token) ?? null) as { descriptor: Descriptor; reasons: string[]; risk_tier: string; requested_at: string; id: string } | null;
    let d = saved?.d ?? req?.descriptor; if (!d) throw new Error("this process did not park the action and the store has no descriptor");
    const exec = execute ?? saved?.execute; if (!exec) throw new Error("resume needs `execute`: this process did not park the action");
    let entry = entryFromDescriptor(d, "ask", req?.risk_tier ?? "high", { reasons: req?.reasons ?? [], rules_fired: ["resume"], target_class: d.target_class, resumed_from: req?.id ?? null });
    [d, entry] = this.afterConfirm(d, entry, dec, req?.requested_at ?? entry.created_at);
    this.resumables.delete(token);
    return this.finish<T>(d, entry, exec as (p: Record<string, unknown>) => Promise<T> | T, saved?.spec ?? {}, { decision: "ask", risk_tier: entry.risk_tier, reasons: entry.reasons, target_class: d.target_class, rules_fired: ["resume"], approvers: [], approver_members: [], hold: false }, dec);
  }

  /** API-only floor: record something that already happened. */
  async attest(opts: { system?: string; verb?: Verb; target?: string; params?: Record<string, unknown>; result?: unknown; verified?: boolean | null; evidence?: Record<string, unknown>; error?: string; agent?: string; actor?: string; run_id?: string }): Promise<LedgerEntry> {
    const d = descriptor({ system: opts.system ?? "unknown", verb: opts.verb ?? "write", target: opts.target ?? null, params: jsonable(opts.params ?? {}) as Record<string, unknown>, actor: opts.actor ?? this.actor ?? null, agent: opts.agent ?? this.agent ?? null, run_id: opts.run_id ?? this.runId, source: "api" });
    const pol = this.policy.evaluate(d); d.target_class = pol.target_class;
    const entry = entryFromDescriptor(d, "recorded", pol.risk_tier, { reasons: pol.reasons, rules_fired: pol.rules_fired, target_class: pol.target_class });
    entry.execution = { status: opts.error ? "failed" : "done", result_hash: opts.result == null ? null : shortHash(jsonable(opts.result)), result_preview: preview(opts.result), error: opts.error ?? null };
    if (opts.verified === true) entry.verification = { level: "verified-custom", method: "caller", matched: true, evidence: opts.evidence ?? {}, checked_at: new Date().toISOString() };
    else if (opts.verified === false) entry.verification = { level: "unverified", method: "caller", matched: false, evidence: opts.evidence ?? {}, checked_at: new Date().toISOString() };
    else entry.verification = await verify(d, opts.result);
    return this.ledger.append(entry);
  }
}

export function only(args: Record<string, unknown>, p: Record<string, unknown>) { return Object.fromEntries(Object.entries(p).filter(([k]) => k in args)); }
export function jsonable(v: unknown): unknown {
  if (v == null || ["string", "number", "boolean"].includes(typeof v)) return v;
  if (Array.isArray(v)) return v.map(jsonable);
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "object") return Object.fromEntries(Object.entries(v as Record<string, unknown>).filter(([k]) => !k.startsWith("_")).map(([k, x]) => [k, jsonable(x)]));
  return String(v);
}
