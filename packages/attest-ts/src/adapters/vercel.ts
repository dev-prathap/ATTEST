/** Vercel AI SDK: wrap `tool()` definitions so `execute` runs through Attest. */
import type { ActionSpec, Attest } from "../core.js";
import { ActionPending, ActionRefused, ActionRejected } from "../core.js";
import { detect } from "../registry.js";

type ToolLike = { description?: string; execute?: (args: never, options: never) => unknown };
export function attested<T extends ToolLike>(at: Attest, name: string, spec: ActionSpec, t: T, opts: { raiseOnBlock?: boolean } = {}): T {
  const run = t.execute; if (!run) return t;
  return {
    ...t,
    execute: async (args: Record<string, unknown>, options: unknown) => {
      const det = detect({ system: spec.system, verb: spec.verb, toolName: name });
      const d = at.describe(det, spec, args); d.extra.framework = "vercel-ai";
      try { return (await at.runAction(d, p => (run as (a: unknown, o: unknown) => unknown)({ ...args, ...Object.fromEntries(Object.entries(p).filter(([k]) => k in args)) }, options), det.recognised, spec)).result; }
      catch (e) {
        if (opts.raiseOnBlock) throw e;
        if (e instanceof ActionPending) return { status: "pending_confirmation", resume_token: e.resumeToken };
        if (e instanceof ActionRefused) return { error: `attest refused this action: ${e.reasons.join("; ")}` };
        if (e instanceof ActionRejected) return { error: `attest: a human rejected this action${e.note ? ` (${e.note})` : ""}` };
        throw e;
      }
    },
  } as T;
}
export function attestedTools<T extends Record<string, ToolLike>>(at: Attest, tools: T, mapping: Record<string, ActionSpec>, opts: { raiseOnBlock?: boolean } = {}): T {
  return Object.fromEntries(Object.entries(tools).map(([name, t]) => [name, attested(at, name, mapping[name] ?? {}, t, opts)])) as T;
}
