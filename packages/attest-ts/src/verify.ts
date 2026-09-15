/** Verification ladder + drivers: ack (L1), custom (L2), convention read-back (L3), recipes for Gmail / Slack / HubSpot. */
import { shortHash } from "./canonical.js";
import type { Descriptor } from "./descriptor.js";
import type { VerificationRecord } from "./ledger.js";

const ID_KEYS = ["id", "ts", "message_id", "messageId", "thread_id", "threadId", "resource_name", "key", "uuid", "uid", "url", "permalink", "number"];
const OK_KEYS = ["ok", "success", "sent", "created", "updated", "deleted", "accepted"];
const STATUS_OK = new Set(["ok", "success", "succeeded", "sent", "created", "updated", "done", "completed", "accepted", "queued", "delivered", "active", "confirmed"]);

export function firstId(result: unknown): string | null {
  if (result == null) return null;
  if (typeof result === "string" || typeof result === "number") return String(result);
  if (typeof result !== "object") return null;
  const r = result as Record<string, unknown>;
  for (const k of ["id", "Id", "ID", "_id", "uuid", "key", "record_id", "recordId", "object_id", "objectId"]) if (r[k] != null && r[k] !== "") return String(r[k]);
  for (const [k, v] of Object.entries(r)) if ((k.endsWith("_id") || k.endsWith("Id")) && v != null && v !== "") return String(v);
  for (const k of ["data", "result", "object", "record"]) if (r[k] && typeof r[k] === "object") { const inner = firstId(r[k]); if (inner) return inner; }
  return null;
}

function nestedId(obj: unknown, depth: number): string | null {
  if (depth === 0 || !obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  const r = obj as Record<string, unknown>;
  for (const k of ID_KEYS) if (r[k] != null && r[k] !== "" && r[k] !== 0 && typeof r[k] !== "object") return String(r[k]).slice(0, 120);
  for (const v of Object.values(r)) if (v && typeof v === "object" && !Array.isArray(v)) { const f = nestedId(v, depth - 1); if (f) return f; }
  return null;
}

export function acknowledged(result: unknown): [boolean, Record<string, unknown>] {
  if (result == null) return [false, { detail: "no result" }];
  const ev: Record<string, unknown> = {};
  if (typeof result === "object" && !Array.isArray(result)) {
    const r = result as Record<string, unknown>;
    if (r.error && Object.keys(r).length <= 2) return [false, { error: String(r.error).slice(0, 200) }];
    for (const k of OK_KEYS) if (r[k] === false) return [false, { [k]: false }];
    for (const k of ID_KEYS) if (r[k] != null && r[k] !== "" && r[k] !== 0) ev[k] = String(r[k]).slice(0, 120);
    for (const k of ["status", "state", "result"]) { const v = r[k]; if (typeof v === "string" && STATUS_OK.has(v.toLowerCase())) ev[k] = v; else if (typeof v === "number" && v >= 200 && v < 300) ev[k] = v; }
    for (const k of OK_KEYS) if (r[k] === true) ev[k] = true;
    for (const [k, v] of Object.entries(r)) if ((k.endsWith("_id") || k.endsWith("Id")) && v != null && v !== "" && !(k in ev)) ev[k] = String(v).slice(0, 120);
    if (!Object.keys(ev).length) { const nested = nestedId(r, 3); if (nested) ev.id = nested; }
    return [Object.keys(ev).length > 0, Object.keys(ev).length ? ev : { detail: "response carried no id or success status" }];
  }
  if (typeof result === "object" && "status" in (result as object)) { const s = (result as { status: number }).status; return [s >= 200 && s < 300, { status_code: s }]; }
  if (typeof result === "boolean") return [result, { bool: result }];
  if (Array.isArray(result)) return [result.length > 0, { count: result.length }];
  return [String(result) !== "", { value: String(result).slice(0, 120) }];
}

export interface MatchReport { matched: boolean; exists: boolean; fields: Record<string, { want: unknown; got: unknown; ok: boolean }>; checks: Record<string, boolean>; notes: string[] }
export const report = (): MatchReport => ({ matched: true, exists: true, fields: {}, checks: {}, notes: [] });
export function field(r: MatchReport, name: string, want: unknown, got: unknown, ok?: boolean) { const o = ok ?? equal(want, got); r.fields[name] = { want, got, ok: o }; if (!o) r.matched = false; return o; }
export function check(r: MatchReport, name: string, ok: boolean) { r.checks[name] = ok; if (!ok) r.matched = false; return ok; }
export const compared = (r: MatchReport) => Object.keys(r.fields).length + Object.keys(r.checks).length;
export function evidenceOf(r: MatchReport): Record<string, unknown> {
  const failed = [...Object.entries(r.fields).filter(([, v]) => !v.ok).map(([k]) => k), ...Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k)];
  return { exists: r.exists, compared: compared(r), ...(Object.keys(r.fields).length ? { fields: r.fields } : {}), ...(Object.keys(r.checks).length ? { checks: r.checks } : {}), ...(failed.length ? { failed } : {}), ...(r.notes.length ? { notes: r.notes } : {}) };
}

const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
export const emails = (v: unknown): string[] => Array.isArray(v) ? v.flatMap(emails) : (String(v ?? "").match(EMAIL) ?? []).map(e => e.toLowerCase());
function norm(v: unknown): unknown {
  if (typeof v === "string") { const s = v.split(/\s+/).join(" ").trim(); return /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(s) ? s.toLowerCase() : s; }
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) return v.map(norm);
  return v;
}
export function equal(want: unknown, got: unknown): boolean {
  if (want == null) return true;
  let a = norm(want), b = norm(got);
  if (Array.isArray(a) && !Array.isArray(b)) b = typeof b === "string" && EMAIL.test(b) ? emails(b) : [b];
  if (Array.isArray(a) && Array.isArray(b)) return a.every(x => (b as unknown[]).some(y => JSON.stringify(y) === JSON.stringify(x)));
  if (typeof a === "string" && typeof b === "string" && /^[\w.+-]+@[\w-]+\.[\w.-]+$/.test(a)) return emails(b).includes(a);
  return JSON.stringify(a) === JSON.stringify(b);
}
export function compareOverlap(r: MatchReport, want: Record<string, unknown>, got: Record<string, unknown>) {
  const sources = [got, ...["properties", "data", "fields", "attributes"].map(k => got[k]).filter(x => x && typeof x === "object")] as Record<string, unknown>[];
  for (const [k, v] of Object.entries(want)) {
    if (["id", "Id", "ID", "_id", "uuid", "key"].includes(k) || v == null || (typeof v === "object" && !Object.keys(v as object).length)) continue;
    for (const src of sources) if (k in src) { field(r, k, v, src[k]); break; }
  }
  return r;
}

export interface ReadBackDriver { name: string; supports(d: Descriptor): boolean; fetch(d: Descriptor, result: unknown): Promise<unknown>; compare(d: Descriptor, result: unknown, fetched: unknown): MatchReport }
export type Fetch = (url: string, init?: RequestInit) => Promise<Response>;
export type HttpGet = (url: string, params?: Record<string, unknown>) => Promise<unknown>;

export class ReadBackError extends Error {}

/** Bearer-token GET helper: `httpGet(url, params)` over fetch. */
export function bearerGet(token?: string, fetchImpl: Fetch = fetch, headers: Record<string, string> = {}): HttpGet {
  return async (url, params) => {
    if (params) url += (url.includes("?") ? "&" : "?") + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)])).toString();
    const res = await fetchImpl(url, { headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers } });
    if (res.status === 404) throw new ReadBackError("HTTP 404");
    if (!res.ok) throw new ReadBackError(`GET ${url.split("?")[0]} → HTTP ${res.status}`);
    const text = await res.text();
    try { return text ? JSON.parse(text) : {}; } catch { throw new ReadBackError("non-JSON response"); }
  };
}

/** Convention driver: POST /x ⇒ GET /x/{id}; PATCH/PUT /x/{id} ⇒ GET same URL. */
export class ConventionDriver implements ReadBackDriver {
  name = "convention";
  constructor(private httpGet: HttpGet) {}
  supports(d: Descriptor) { return ["create", "update", "upload", "write"].includes(d.verb) && !!d.extra.url; }
  readUrl(d: Descriptor, result: unknown): string | null {
    const url = String(d.extra.url ?? "").split("?")[0].replace(/\/$/, ""); if (!url) return null;
    const method = String(d.extra.method ?? "POST").toUpperCase(); const rid = firstId(result);
    if (method === "POST" && ["create", "upload", "write"].includes(d.verb)) return rid ? `${url}/${rid}` : null;
    return url;
  }
  async fetch(d: Descriptor, result: unknown) { const u = this.readUrl(d, result); if (!u) return null; try { return await this.httpGet(u); } catch (e) { if (e instanceof ReadBackError && e.message.includes("404")) return null; throw e; } }
  compare(d: Descriptor, result: unknown, fetched: unknown): MatchReport {
    const r = report();
    if (!fetched || typeof fetched !== "object") { check(r, "record:exists", fetched != null); return r; }
    const want = firstId(result), got = firstId(fetched);
    if (want && got) field(r, "id", want, got, want === got);
    compareOverlap(r, d.params, fetched as Record<string, unknown>);
    if (compared(r) === 0) { check(r, "record:exists", true); r.notes.push("existence only — no intended field present in the read-back"); }
    return r;
  }
}

/** Reviewed recipes (Gmail send, Slack send, HubSpot object) over `readers: {system: token | httpGet}`. */
export class RecipeDriver implements ReadBackDriver {
  name = "recipe";
  constructor(private readers: Record<string, string | HttpGet>, private fetchImpl: Fetch = fetch) {}
  private get(system: string, extraHeaders: Record<string, string> = {}): HttpGet | null {
    const r = this.readers[system]; if (!r) return null;
    return typeof r === "string" ? bearerGet(r, this.fetchImpl, extraHeaders) : r;
  }
  supports(d: Descriptor) {
    return (d.system === "gmail" && ["send", "reply"].includes(d.verb)) || (d.system === "slack" && ["send", "reply"].includes(d.verb)) ||
      (d.system === "hubspot" && ["create", "update", "write"].includes(d.verb) && !!hubspotType(d));
  }
  async fetch(d: Descriptor, result: unknown) {
    const get = this.get(d.system); if (!get) return null;
    const r = (result ?? {}) as Record<string, unknown>;
    if (d.system === "gmail") { const id = firstId(result); return id ? get(`https://gmail.googleapis.com/gmail/v1/users/me/messages/${id}`, { format: "metadata", metadataHeaders: "To" }) : null; }
    if (d.system === "slack") {
      const ts = r.ts ?? (r.message as Record<string, unknown> | undefined)?.ts, ch = r.channel ?? d.params.channel ?? d.params.channel_id; if (!ts || !ch) return null;
      const out = await get("https://slack.com/api/conversations.history", { channel: String(ch), latest: String(ts), inclusive: "true", limit: 1 }) as Record<string, unknown>;
      const msgs = (out.messages as Record<string, unknown>[]) ?? []; return msgs.length && String(msgs[0].ts) === String(ts) ? msgs[0] : null;
    }
    const type = hubspotType(d)!, id = String(d.params.object_id ?? d.params.id ?? d.params[`${type.replace(/s$/, "")}_id`] ?? firstId(result) ?? "");
    if (!id) return null;
    const props = Object.keys(hubspotProps(d));
    return get(`https://api.hubapi.com/crm/v3/objects/${type}/${id}`, props.length ? { properties: props.join(",") } : undefined);
  }
  compare(d: Descriptor, result: unknown, fetched: unknown): MatchReport {
    const r = report(); const f = fetched as Record<string, unknown>;
    if (d.system === "gmail") {
      const labels = (f.labelIds as string[]) ?? []; check(r, "label:SENT", labels.includes("SENT"));
      const headers = Object.fromEntries((((f.payload as Record<string, unknown>)?.headers as { name: string; value: string }[]) ?? []).map(h => [h.name.toLowerCase(), h.value]));
      const got = [...emails(headers.to ?? ""), ...emails(headers.cc ?? "")];
      for (const e of [...emails(d.params.to), ...emails(d.params.cc)]) field(r, `recipient:${e}`, e, got.join(", "), got.includes(e));
      if (d.params.subject && headers.subject != null) field(r, "subject", d.params.subject, headers.subject);
      return r;
    }
    if (d.system === "slack") {
      const want = (result as Record<string, unknown>)?.ts; field(r, "ts", want, f.ts, String(want) === String(f.ts));
      if (d.params.text != null && "text" in f) field(r, "text", d.params.text, f.text);
      return r;
    }
    const want = String(d.params.object_id ?? d.params.id ?? firstId(result) ?? ""); if (want && f.id != null) field(r, "id", want, f.id, want === String(f.id));
    compareOverlap(r, hubspotProps(d), f);
    if (compared(r) === 0) check(r, "object:exists", true);
    return r;
  }
}
const HS = ["contacts", "deals", "companies", "tickets", "products", "notes", "tasks"];
function hubspotType(d: Descriptor): string | null {
  const explicit = d.params.object_type ?? d.params.objectType; if (explicit) { const v = String(explicit).toLowerCase(); return v.endsWith("s") ? v : v === "company" ? "companies" : v + "s"; }
  const t = (d.target ?? "").toLowerCase();
  for (const type of HS) if (t.includes(type) || t.includes(type.slice(0, -1)) || (type === "companies" && t.includes("company"))) return type;
  for (const k of Object.keys(d.params)) { const base = k.toLowerCase().replace(/_?id$/, ""); if (base === "company") return "companies"; if (HS.includes(base + "s")) return base + "s"; }
  return null;
}
function hubspotProps(d: Descriptor): Record<string, unknown> {
  if (d.params.properties && typeof d.params.properties === "object") return d.params.properties as Record<string, unknown>;
  const skip = new Set(["object_type", "objectType", "id", "object_id", "contact_id", "deal_id", "company_id", "ticket_id", "associations"]);
  return Object.fromEntries(Object.entries(d.params).filter(([k, v]) => !skip.has(k) && (v == null || typeof v !== "object")));
}

export type Custom = (result: unknown, d: Descriptor) => unknown | Promise<unknown>;

function record(level: VerificationRecord["level"], method: string, matched: boolean | null, evidence: Record<string, unknown>): VerificationRecord {
  return { level, method, matched, evidence, checked_at: new Date().toISOString() };
}
function degrade(result: unknown, method: string, error: string): VerificationRecord {
  const [ok, ev] = acknowledged(result); return record(ok ? "acknowledged" : "attested-only", method, null, { ...ev, check_error: error });
}

export async function verify(d: Descriptor, result: unknown, opts: { custom?: Custom; drivers?: ReadBackDriver[] } = {}): Promise<VerificationRecord> {
  for (const drv of opts.drivers ?? []) {
    if (!drv.supports(d)) continue;
    const method = `read-back:${drv.name}`;
    let fetched: unknown;
    try { fetched = await drv.fetch(d, result); } catch (e) { return degrade(result, method, `fetch failed: ${(e as Error).message}`); }
    if (fetched == null) return degrade(result, method, "read-back returned nothing to compare");
    let rep: MatchReport;
    try { rep = drv.compare(d, result, fetched); } catch (e) { return degrade(result, method, `compare failed: ${(e as Error).message}`); }
    if (!rep.matched) return record("unverified", method, false, evidenceOf(rep));
    const intended = [...Object.keys(rep.fields).filter(k => k !== "id"), ...Object.keys(rep.checks).filter(k => !k.endsWith(":exists"))];
    if (!intended.length) return record("acknowledged", method, null, { ...evidenceOf(rep), detail: "read-back found the record; no intended field could be compared" });
    return record("verified", method, true, evidenceOf(rep));
  }
  if (opts.custom) {
    let out: unknown;
    try { out = await opts.custom(result, d); } catch (e) { return degrade(result, "custom", `${(e as Error).name}: ${(e as Error).message}`); }
    let evidence: Record<string, unknown> = {};
    if (Array.isArray(out) && out.length === 2 && typeof out[1] === "object") { evidence = out[1] as Record<string, unknown>; out = out[0]; }
    if (out == null) return degrade(result, "custom", "verify function returned null");
    return out ? record("verified-custom", "custom", true, evidence) : record("unverified", "custom", false, Object.keys(evidence).length ? evidence : { detail: "verify function returned false" });
  }
  const [ok, ev] = acknowledged(result);
  return record(ok ? "acknowledged" : "attested-only", ok ? "ack" : "none", null, ev);
}
