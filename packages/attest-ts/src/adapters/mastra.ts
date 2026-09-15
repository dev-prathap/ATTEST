/** Mastra: tools from `createTool({ id, execute: async ({ context }) => … })`. */
import type { ActionSpec, Attest } from "../core.js";
import { ActionPending, ActionRefused, ActionRejected } from "../core.js";
import { detect } from "../registry.js";

type ToolLike = { id: string; description?: string; execute?: (input: { context: Record<string, unknown> } & Record<string, unknown>, options?: unknown) => Promise<unknown> };
export function wrapTool<T extends ToolLike>(at: Attest, t: T, mapping: Record<string, ActionSpec> = {}, opts: { raiseOnBlock?: boolean } = {}): T {
  const spec = mapping[t.id] ?? {}; const run = t.execute; if (!run) return t;
  const execute = async (input: { context: Record<string, unknown> } & Record<string, unknown>, options?: unknown) => {
    const args = input.context ?? {};
    const det = detect({ system: spec.system, verb: spec.verb, toolName: t.id });
    const d = at.describe(det, spec, args); d.extra.framework = "mastra";
    try { return (await at.runAction(d, p => run({ ...input, context: { ...args, ...Object.fromEntries(Object.entries(p).filter(([k]) => k in args)) } }, options), det.recognised, spec)).result; }
    catch (e) {
      if (opts.raiseOnBlock) throw e;
      if (e instanceof ActionPending) return { status: "pending_confirmation", resume_token: e.resumeToken };
      if (e instanceof ActionRefused) return { error: `attest refused this action: ${e.reasons.join("; ")}` };
      if (e instanceof ActionRejected) return { error: `attest: a human rejected this action${e.note ? ` (${e.note})` : ""}` };
      throw e;
    }
  };
  return { ...t, execute } as T;
}
export const wrapTools = <T extends ToolLike>(at: Attest, tools: T[], mapping: Record<string, ActionSpec> = {}, opts: { raiseOnBlock?: boolean } = {}) => tools.map(t => wrapTool(at, t, mapping, opts));
