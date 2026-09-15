import { newId, shortHash } from "./canonical.js";
import data from "./registry-data.json" with { type: "json" };

export type Verb = "read" | "search" | "get" | "list" | "create" | "update" | "delete" | "send" | "reply" | "share" |
  "upload" | "pay" | "approve" | "execute" | "write";
export type RiskTier = "low" | "medium" | "high" | "very_high";
export type TargetClass = "internal" | "known" | "external" | "none";
export const WRITE_VERBS = new Set<string>(data.write_verbs);

export interface Descriptor {
  id: string; system: string; verb: Verb; target?: string | null; target_class: TargetClass;
  params: Record<string, unknown>; actor?: string | null; owner?: string | null; agent?: string | null;
  run_id?: string | null; risk?: RiskTier | null; result?: unknown; source: string; extra: Record<string, unknown>;
  created_at: string;
}

export function descriptor(init: Partial<Descriptor> & { system?: string; verb?: Verb }): Descriptor {
  return {
    id: init.id ?? newId("act"), system: init.system ?? "unknown", verb: init.verb ?? "write", target: init.target ?? null,
    target_class: init.target_class ?? "none", params: init.params ?? {}, actor: init.actor ?? null, owner: init.owner ?? null,
    agent: init.agent ?? null, run_id: init.run_id ?? null, risk: init.risk ?? null, result: init.result,
    source: init.source ?? "manual", extra: init.extra ?? {}, created_at: init.created_at ?? new Date().toISOString(),
  };
}

export const paramsHash = (d: Descriptor) => shortHash(d.params);
export const isWrite = (d: Descriptor) => WRITE_VERBS.has(d.verb);
export const qualifiedName = (d: Descriptor) => `${d.system}.${d.verb}` + (d.target ? `:${d.target}` : "");

/** Descriptor as stored: never raw params or result. */
export function toLedger(d: Descriptor): Record<string, unknown> {
  const { params: _p, result: _r, created_at: _c, ...rest } = d;
  return { ...rest, params_hash: paramsHash(d) };
}
