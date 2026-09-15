/** Policy engine — YAML rules (first match wins) + built-in R0–R4, mirroring the Python engine. */
import YAML from "yaml";
import data from "./registry-data.json" with { type: "json" };
import { registeredDomain, riskFor } from "./registry.js";
import { isWrite, qualifiedName, type Descriptor, type TargetClass } from "./descriptor.js";

export type Decision = "act" | "ask" | "refuse";
export interface Rule { match: Record<string, string[]>; decision: Decision; approvers: string[]; reason?: string; name?: string }
export interface PolicyDoc { rules: Rule[]; groups: Record<string, string[]>; agentRules: Record<string, Rule[]> }
export interface PolicyContext {
  orgRule?: (d: Descriptor) => "allowed" | "approval_required" | "blocked";
  orgDomain?: () => string | null | undefined;
  isKnownDomain?: (domain: string) => boolean;
  internalDomains?: string[];
}
export interface PolicyResult {
  decision: Decision; risk_tier: string; reasons: string[]; target_class: TargetClass; rules_fired: string[];
  approvers: string[]; approver_members: string[]; hold: boolean;
}

const MATCH_KEYS = new Set(["system", "verb", "target", "target_class", "target_domain", "actor", "agent", "risk", "action"]);
const RECIPIENT_KEYS = ["to", "cc", "bcc", "email", "emails", "attendees", "recipients", "recipient", "user", "users", "share_with", "invitees", "members"];
const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
const PLACEHOLDER = /\[[^\]]+\]|\{\{[^}]+\}\}|<[A-Z_ ]{3,}>/;
const RANK: Record<string, number> = { none: 0, internal: 1, known: 2, external: 3 };
const LABEL: Record<string, string> = { low: "Low", medium: "Medium", high: "High", very_high: "Very high" };

const listify = (v: unknown): string[] => v == null ? [] : Array.isArray(v) ? v.map(String) : [String(v)];

export function parseRules(items: unknown): Rule[] {
  const arr = Array.isArray(items) ? items : ((items as Record<string, unknown>)?.policies ?? (items as Record<string, unknown>)?.rules ?? []) as unknown[];
  return arr.map((item, i) => {
    const it = item as Record<string, unknown>;
    const match = (it.match ?? {}) as Record<string, unknown>;
    const bad = Object.keys(match).filter(k => !MATCH_KEYS.has(k));
    if (bad.length) throw new Error(`policy #${i}: unknown match keys ${bad.join(", ")}`);
    const decision = String(it.decision ?? "").toLowerCase();
    if (!["act", "ask", "refuse"].includes(decision)) throw new Error(`policy #${i}: decision must be act|ask|refuse`);
    return { match: Object.fromEntries(Object.entries(match).map(([k, v]) => [k, listify(v)])), decision: decision as Decision,
      approvers: listify(it.approvers), reason: it.reason as string | undefined, name: it.name as string | undefined };
  });
}

export function parseDoc(doc: unknown): PolicyDoc {
  if (Array.isArray(doc) || !doc) return { rules: parseRules(doc ?? []), groups: {}, agentRules: {} };
  const d = doc as Record<string, unknown>;
  const groups = Object.fromEntries(Object.entries((d.groups ?? {}) as Record<string, unknown>).map(([k, v]) => [k, listify(v)]));
  const agentRules: Record<string, Rule[]> = {};
  for (const [agent, spec] of Object.entries((d.agents ?? {}) as Record<string, unknown>)) {
    const rules = parseRules((spec as Record<string, unknown>)?.policies ?? spec);
    for (const r of rules) { r.name = r.name ?? `agent:${agent}`; r.match.agent = r.match.agent ?? [agent]; }
    agentRules[agent] = rules;
  }
  return { rules: parseRules(d), groups, agentRules };
}

export const loadDoc = (text: string): PolicyDoc => parseDoc(YAML.parse(text) ?? {});
export const defaultDoc = (): PolicyDoc => loadDoc(data.default_policy_yaml);

function addresses(params: Record<string, unknown>, target?: string | null): string[] {
  const out: string[] = [];
  for (const k of RECIPIENT_KEYS) {
    const v = params[k];
    for (const x of Array.isArray(v) ? v : v ? [v] : []) out.push(...(String(x).match(EMAIL) ?? []));
  }
  if (target) out.push(...(target.match(EMAIL) ?? []));
  return [...new Map(out.map(a => [a.toLowerCase(), a])).values()];
}

function targetDomains(d: Descriptor): string[] {
  const out = new Set(addresses(d.params, d.target).map(e => registeredDomain(e.split("@").pop()!)));
  if (d.target && !d.target.includes("@") && d.target.includes(".") && !d.target.includes("/")) out.add(registeredDomain(d.target));
  return [...out].filter(Boolean).sort();
}

function glob(value: string, patterns: string[]): boolean {
  return patterns.some(p => p.includes("*") && new RegExp("^" + p.split("*").map(s => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$").test(value));
}

function matches(rule: Rule, d: Descriptor, tier: string, targetClass: string): boolean {
  for (const [key, wanted] of Object.entries(rule.match)) {
    let have: string[];
    switch (key) {
      case "system": have = [d.system]; break;
      case "verb": have = [d.verb]; break;
      case "target": case "target_class": have = [targetClass]; break;
      case "target_domain": have = targetDomains(d); break;
      case "actor": have = [d.actor ?? ""]; break;
      case "agent": have = [d.agent ?? ""]; break;
      case "risk": have = [tier]; break;
      case "action": have = [qualifiedName(d), `${d.system}.${d.verb}`]; break;
      default: return false;
    }
    const w = wanted.map(x => x.toLowerCase());
    if (!have.some(h => w.includes(h.toLowerCase()) || glob(h.toLowerCase(), w))) return false;
  }
  return true;
}

export class PolicyEngine {
  doc: PolicyDoc; ctx: PolicyContext;
  constructor(doc?: PolicyDoc | null, ctx?: PolicyContext) { this.doc = doc ?? defaultDoc(); this.ctx = ctx ?? {}; }
  static fromYaml(text: string, ctx?: PolicyContext) { return new PolicyEngine(loadDoc(text), ctx); }

  resolveApprovers(names: string[]): string[] {
    const out: string[] = [];
    for (const n of names) for (const m of this.doc.groups[n] ?? [n]) if (!out.includes(m)) out.push(m);
    return out;
  }

  evaluate(d: Descriptor, recognised = true): PolicyResult {
    const actionId = `${d.system}_${d.verb}` + (d.target ? `_${d.target}` : "");
    const tier = d.risk ?? riskFor(d.verb, recognised, actionId);
    const out: PolicyResult = { decision: "act", risk_tier: tier, reasons: [], target_class: "none", rules_fired: [], approvers: [], approver_members: [], hold: false };
    const rule = (this.ctx.orgRule?.(d) ?? "allowed").toLowerCase();
    if (rule === "blocked") { out.decision = "refuse"; out.rules_fired.push("R0"); out.reasons.push(`'${qualifiedName(d)}' is blocked by your organisation's policy`); return out; }
    if (d.owner && d.actor && d.owner !== d.actor) { out.rules_fired.push("R1"); out.reasons.push(`Runs on ${d.owner}'s connection on behalf of ${d.actor}`); }
    if (isWrite(d)) {
      const own = new Set((this.ctx.internalDomains ?? []).map(registeredDomain));
      for (const c of [this.ctx.orgDomain?.(), d.actor?.includes("@") ? d.actor.split("@").pop() : null]) if (c) own.add(registeredDomain(c));
      const emails = addresses(d.params, d.target);
      if (emails.length) {
        let worst = "none"; const reasons: string[] = [];
        for (const e of emails) {
          const dom = registeredDomain(e.split("@").pop()!);
          let kind: string, why: string;
          if (dom && own.has(dom)) { kind = "internal"; why = `${e} is internal`; }
          else if (dom && this.ctx.isKnownDomain?.(dom)) { kind = "known"; why = `${dom} is a known relationship`; }
          else { kind = "external"; why = `${e} is external (${dom || "unknown domain"}) — not internal or a known relationship`; }
          reasons.push(why); if (RANK[kind] > RANK[worst]) worst = kind;
        }
        out.target_class = worst as TargetClass; out.rules_fired.push("R2"); out.reasons.push(reasons.join("; "));
      }
      for (const [k, v] of Object.entries(d.params)) if (typeof v === "string" && PLACEHOLDER.test(v)) {
        out.decision = "ask"; out.hold = true; out.rules_fired.push("R3");
        out.reasons.push(`'${k}' has unfilled placeholder(s) — fill before it leaves`); return out;
      }
    }
    if (rule === "approval_required") { out.decision = "ask"; out.rules_fired.push("R0"); out.reasons.push("Your organisation requires approval for this action"); return out; }
    const candidates = [...(d.agent ? this.doc.agentRules[d.agent] ?? [] : []), ...this.doc.rules];
    for (const r of candidates) if (matches(r, d, tier, out.target_class)) {
      out.rules_fired.push(`policy:${r.name ?? r.decision}`); out.reasons.push(r.reason ?? `matched policy rule ${r.name ?? JSON.stringify(r.match)}`);
      out.approvers = [...r.approvers]; out.approver_members = this.resolveApprovers(r.approvers); out.decision = r.decision; return out;
    }
    out.rules_fired.push("R4");
    if (tier === "low" || tier === "medium") { out.decision = "act"; out.reasons.push(`${LABEL[tier]} risk — no confirmation needed`); }
    else { out.decision = "ask"; out.reasons.push(`${LABEL[tier]} risk → requires explicit confirmation`); }
    return out;
  }
}
