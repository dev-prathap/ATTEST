/** Hash-chained ledger: same entry payload and chain construction as the Python SDK, stored as JSON lines. */
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";
import { canonicalJson, newId, sha256, shortHash } from "./canonical.js";
import { paramsHash, toLedger, type Descriptor } from "./descriptor.js";

export const GENESIS = "0".repeat(64);
export type Level = "verified" | "verified-custom" | "acknowledged" | "attested-only" | "unverified";
const PREVIEW_KEYS = new Set(["to", "cc", "recipient", "recipients", "channel", "channel_id", "id", "name", "title", "subject",
  "email", "url", "path", "key", "ts", "message_id", "thread_id", "resource_name", "status", "ok", "amount", "currency", "role",
  "labels", "dealname", "properties"]);

export function preview(obj: unknown): unknown {
  if (obj == null) return null;
  if (typeof obj === "object" && !Array.isArray(obj)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      if (PREVIEW_KEYS.has(k) || k.endsWith("_id") || k.endsWith("Id")) {
        if (v && typeof v === "object") out[k] = JSON.stringify(v).length > 120 ? shortHash(v) : v;
        else if (typeof v === "string" && v.length > 120) out[k] = v.slice(0, 120) + "…";
        else out[k] = v;
      }
    }
    return out;
  }
  const s = String(obj); return s.length > 120 ? s.slice(0, 120) + "…" : s;
}

export interface ConfirmRecord { status: string; channel?: string | null; approver?: string | null; requested_at?: string | null; decided_at?: string | null; edits?: Record<string, unknown> | null; note?: string | null }
export interface ExecutionRecord { status: string; result_hash?: string | null; result_preview?: unknown; error?: string | null; started_at?: string | null; finished_at?: string | null; duration_ms?: number | null }
export interface VerificationRecord { level: Level; method?: string | null; matched?: boolean | null; evidence: Record<string, unknown>; checked_at?: string | null }

export interface LedgerEntry {
  id: string; action_id: string; run_id?: string | null; agent?: string | null; actor?: string | null;
  descriptor: Record<string, unknown>; params_hash: string; params_preview?: unknown; decision: string; risk_tier: string;
  reasons: string[]; rules_fired: string[]; target_class: string; confirm: ConfirmRecord; execution?: ExecutionRecord | null;
  verification: VerificationRecord; resumed_from?: string | null; created_at: string; sdk: string;
  seq?: number; prev_hash?: string; payload_hash?: string; hash?: string;
}

export function entryFromDescriptor(d: Descriptor, decision: string, riskTier: string, extra: Partial<LedgerEntry> = {}): LedgerEntry {
  return {
    id: newId("led"), action_id: d.id, run_id: d.run_id ?? null, agent: d.agent ?? null, actor: d.actor ?? null,
    descriptor: toLedger(d), params_hash: paramsHash(d), params_preview: preview(d.params), decision, risk_tier: riskTier,
    reasons: [], rules_fired: [], target_class: d.target_class, confirm: { status: "not_required" }, execution: null,
    verification: { level: "attested-only", evidence: {} }, resumed_from: null, created_at: new Date().toISOString(),
    sdk: "attest-ts/0.1.0", ...extra,
  };
}

export const payloadOf = (e: LedgerEntry): Record<string, unknown> => { const { seq: _s, prev_hash: _p, payload_hash: _ph, hash: _h, ...rest } = e; return rest; };
export const payloadHash = (payload: unknown) => sha256(canonicalJson(payload));
export const entryHash = (prev: string, seq: number, ph: string) => sha256(`${prev}|${seq}|${ph}`);

export interface ChainReport { ok: boolean; checked: number; broken_at?: number | null; problems: string[] }

export function verifyChain(rows: LedgerEntry[], anchor?: [number, string]): ChainReport {
  let prev = GENESIS, expected = 1;
  if (anchor) { prev = anchor[1]; expected = anchor[0] + 1; rows = rows.filter(r => (r.seq ?? 0) > anchor[0]); }
  for (const r of rows) {
    const seq = r.seq!;
    if (seq !== expected) return { ok: false, checked: seq - 1, broken_at: seq, problems: [`seq gap: expected ${expected}, found ${seq}`] };
    if (r.prev_hash !== prev) return { ok: false, checked: seq - 1, broken_at: seq, problems: [`prev_hash mismatch at seq ${seq}`] };
    const ph = payloadHash(payloadOf(r));
    if (ph !== r.payload_hash) return { ok: false, checked: seq - 1, broken_at: seq, problems: [`payload altered at seq ${seq}`] };
    const h = entryHash(prev, seq, ph);
    if (h !== r.hash) return { ok: false, checked: seq - 1, broken_at: seq, problems: [`hash mismatch at seq ${seq}`] };
    prev = h; expected = seq + 1;
  }
  return { ok: true, checked: expected - 1, broken_at: null, problems: [] };
}

export interface Ledger { append(e: LedgerEntry): LedgerEntry; entries(opts?: { run_id?: string; level?: string; limit?: number; newestFirst?: boolean }): LedgerEntry[]; last(): LedgerEntry | null; count(): number; verifyChain(): ChainReport }

/** Append-only JSON-lines file (or in memory with path ":memory:"). One process per file. */
export class FileLedger implements Ledger {
  private rows: LedgerEntry[] = [];
  constructor(public path = ".attest/ledger.jsonl") {
    if (path !== ":memory:" && existsSync(path)) this.rows = readFileSync(path, "utf8").split("\n").filter(Boolean).map(l => JSON.parse(l));
  }
  append(e: LedgerEntry): LedgerEntry {
    const tail = this.rows[this.rows.length - 1];
    const seq = tail ? tail.seq! + 1 : 1, prev = tail ? tail.hash! : GENESIS;
    const payload = payloadOf(e), ph = payloadHash(payload), h = entryHash(prev, seq, ph);
    const row = { ...e, seq, prev_hash: prev, payload_hash: ph, hash: h };
    this.rows.push(row);
    if (this.path !== ":memory:") { mkdirSync(dirname(this.path), { recursive: true }); appendFileSync(this.path, JSON.stringify(row) + "\n"); }
    return row;
  }
  entries(opts: { run_id?: string; level?: string; limit?: number; newestFirst?: boolean } = {}): LedgerEntry[] {
    let out = this.rows.filter(r => (!opts.run_id || r.run_id === opts.run_id) && (!opts.level || r.verification.level === opts.level));
    if (opts.newestFirst) out = [...out].reverse();
    return opts.limit ? out.slice(0, opts.limit) : out;
  }
  last() { return this.rows[this.rows.length - 1] ?? null; }
  count() { return this.rows.length; }
  verifyChain() { return verifyChain(this.rows); }
  export(fmt: "json" | "jsonl" = "json") { return fmt === "jsonl" ? this.rows.map(r => JSON.stringify(r)).join("\n") : JSON.stringify(this.rows, null, 2); }
}
