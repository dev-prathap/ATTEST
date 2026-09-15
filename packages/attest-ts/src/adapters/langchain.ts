/** LangChain.js: wrap StructuredTool / DynamicStructuredTool instances (anything with `name` and `invoke`). */
import type { ActionSpec, Attest } from "../core.js";
import { ActionPending, ActionRefused, ActionRejected } from "../core.js";
import { detect } from "../registry.js";

type ToolLike = { name: string; description?: string; invoke: (input: unknown, config?: unknown) => Promise<unknown> };
export function wrapTool<T extends ToolLike>(at: Attest, t: T, mapping: Record<string, ActionSpec> = {}, opts: { raiseOnBlock?: boolean } = {}): T {
  const spec = mapping[t.name] ?? {}; const orig = t.invoke.bind(t);
  const invoke = async (input: unknown, config?: unknown) => {
    const args = (input && typeof input === "object" ? input : { input }) as Record<string, unknown>;
    const det = detect({ system: spec.system, verb: spec.verb, toolName: t.name });
    const d = at.describe(det, spec, args); d.extra.framework = "langchain-js";
    try { return (await at.runAction(d, p => orig({ ...args, ...Object.fromEntries(Object.entries(p).filter(([k]) => k in args)) }, config), det.recognised, spec)).result; }
    catch (e) {
      if (opts.raiseOnBlock) throw e;
      if (e instanceof ActionPending) return `attest: pending human confirmation (resume_token=${e.resumeToken})`;
      if (e instanceof ActionRefused) return `attest refused this action: ${e.reasons.join("; ")}`;
      if (e instanceof ActionRejected) return `attest: a human rejected this action${e.note ? ` (${e.note})` : ""}`;
      throw e;
    }
  };
  return Object.assign(Object.create(Object.getPrototypeOf(t)), t, { invoke, _attestWrapped: true }) as T;
}
export const wrapTools = <T extends ToolLike>(at: Attest, tools: T[], mapping: Record<string, ActionSpec> = {}, opts: { raiseOnBlock?: boolean } = {}) => tools.map(t => wrapTool(at, t, mapping, opts));
