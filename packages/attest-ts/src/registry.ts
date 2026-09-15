/** System / verb detection — same data and rules as the Python registry (registry-data.json is exported from it). */
import data from "./registry-data.json" with { type: "json" };
import type { Verb } from "./descriptor.js";

const VERB_MAP = data.verb_map as Record<string, string>;
const GET = new Set(data.get_words), SEARCH = new Set(data.search_words), LIST = new Set(data.list_words);
const MONEY = new Set(data.money_nouns), STRIP = new Set(data.strip_prefix);
const SYSTEMS = new Set(data.systems), ALIASES = data.system_aliases as Record<string, string>;
const RISK: Record<string, string> = data.risk_by_verb;
const OVERRIDES = data.verb_overrides as Record<string, string>;

export interface Detection { system: string; verb: Verb; target: string | null; source: string; recognised: boolean }

const overrides = new Map<string, { system: string; verb: Verb }>();
export function register(name: string, system: string, verb: Verb) { overrides.set(name, { system, verb }); }

export function singular(w: string): string {
  if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
  if (w.endsWith("s") && !w.endsWith("ss") && w.length > 3) return w.slice(0, -1);
  return w;
}

export function tokens(name: string): string[] {
  let n = name.trim();
  if (n.startsWith("mcp__")) n = n.slice(5);
  return n.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/[_\-.:/\s]+/).filter(Boolean).map(t => t.toLowerCase());
}

export function classify(toks: string[]): [Verb, boolean] {
  let t = toks.filter(Boolean);
  while (t.length > 1 && STRIP.has(t[0])) t = t.slice(1);
  let verb: string = "write", ok = false;
  for (const w of t) {
    if (SEARCH.has(w)) { verb = "search"; ok = true; break; }
    if (LIST.has(w)) { verb = "list"; ok = true; break; }
    if (GET.has(w)) { verb = "get"; ok = true; break; }
    if (w in VERB_MAP) { verb = VERB_MAP[w]; ok = true; break; }
  }
  if (["create", "update", "write"].includes(verb) && t.some(w => MONEY.has(singular(w)))) return ["pay", true];
  return [verb as Verb, ok];
}

export function canonicalSystem(name?: string | null): string | null {
  if (!name) return null;
  const key = name.toLowerCase().replace(/[-\s.]/g, "_");
  if (SYSTEMS.has(key)) return key;
  return ALIASES[key] ?? null;
}

export function riskFor(verb: string, recognised = true, actionId?: string): string {
  if (actionId && actionId in (data.risk_overrides as Record<string, string>)) return (data.risk_overrides as Record<string, string>)[actionId];
  if (verb === "delete") return "very_high";
  if (!recognised && !data.read_verbs.includes(verb)) return "high";
  return RISK[verb] ?? "medium";
}

function splitSystem(toks: string[], server?: string | null): [string, string[]] {
  if (server) {
    const sys = canonicalSystem(server) ?? server.toLowerCase().replace(/[-\s]/g, "_");
    if (toks.length && (toks[0] === sys || ALIASES[toks[0]] === sys)) toks = toks.slice(1);
    return [sys, toks];
  }
  for (const n of [2, 1]) {
    if (toks.length >= n) {
      const head = toks.slice(0, n).join("_");
      if (SYSTEMS.has(head) && head !== "unknown") return [head, toks.slice(n)];
      if (head in ALIASES) return [ALIASES[head], toks.slice(n)];
    }
  }
  return ["unknown", toks];
}

function nouns(rest: string[]): string | null {
  const verbish = new Set([...Object.keys(VERB_MAP), ...GET, ...LIST, ...SEARCH]);
  const t = rest.filter(x => !STRIP.has(x));
  const idx = t.findIndex(x => verbish.has(x));
  const remaining = idx < 0 ? t : [...t.slice(0, idx), ...t.slice(idx + 1)];
  return remaining.length ? remaining.join("_") : null;
}

export function detectToolName(name: string, server?: string | null): Detection {
  const toks = tokens(name);
  const [system, rest] = splitSystem(toks, server);
  const actionId = rest.length ? `${system}_${rest.join("_")}` : system;
  let verb: Verb, recognised: boolean;
  if (actionId in OVERRIDES) { verb = OVERRIDES[actionId] as Verb; recognised = true; } else [verb, recognised] = classify(rest);
  return { system, verb, target: nouns(rest), source: "mcp", recognised };
}

export function registeredDomain(host: string): string {
  const parts = host.toLowerCase().replace(/\.$/, "").split(":")[0].split(".");
  if (parts.length < 2) return host;
  const two = parts.slice(-2).join(".");
  if (parts.length >= 3 && ["co.uk", "com.au", "co.in", "co.jp", "com.br", "co.nz", "org.uk", "co.za", "com.sg"].includes(two)) return parts.slice(-3).join(".");
  return two;
}

export function systemForHost(host: string, path = ""): string {
  host = host.toLowerCase();
  for (const { host: h, system, paths } of data.host_systems as { host: string; system: string; paths: Record<string, string> }[]) {
    if (host === h || host.endsWith("." + h)) {
      for (const [prefix, refined] of Object.entries(paths)) if (path.includes(prefix)) return refined;
      return system;
    }
  }
  const reg = registeredDomain(host);
  return (reg.split(".")[0] || "unknown").replace(/-/g, "_");
}

const ID_SEG = /^(\d+|me|primary|\{[^}]+\}|[0-9a-f-]{8,}|[A-Za-z]{1,5}[-_]\d+|(?=.*\d)[A-Za-z0-9_.\-]{5,}|[A-Za-z0-9_-]{20,})$/;
const VERSION = /^v\d+(\.\d+)?$/;
const looksLikeId = (s: string) => ID_SEG.test(s) && !VERSION.test(s);

export function detectUrl(method: string, url: string): Detection {
  method = (method || "GET").toUpperCase();
  const u = new URL(url.includes("://") ? url : "https://" + url);
  const system = systemForHost(u.host, u.pathname);
  const segs = u.pathname.split("/").filter(s => s && !VERSION.test(s));
  const words = segs.filter(s => !looksLikeId(s)).flatMap(tokens);
  let pathVerb: string | null = null, pathWord: string | null = null;
  for (const w of [...words.slice(-3)].reverse()) {
    const v = wordVerb(w);
    if (v && !["create", "update"].includes(v)) { pathVerb = v; pathWord = w; break; }
  }
  let verb: string, recognised = true;
  if (["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (pathVerb === "search" || u.search.includes("q=") || u.search.includes("query=") || words.includes("search")) verb = "search";
    else if (segs.length && looksLikeId(segs[segs.length - 1])) verb = "get";
    else if (words.length && (GET.has(words[words.length - 1]) || LIST.has(words[words.length - 1]))) verb = classify([words[words.length - 1]])[0];
    else verb = "list";
  } else if (method === "DELETE") verb = "delete";
  else if (method === "POST") {
    if (pathVerb && !["get", "list", "search"].includes(pathVerb)) verb = pathVerb;
    else if (segs.length && looksLikeId(segs[segs.length - 1])) verb = "update";
    else verb = "create";
  } else if (["PUT", "PATCH"].includes(method)) verb = pathVerb && ["share", "pay", "approve", "execute", "send", "reply", "upload"].includes(pathVerb) ? pathVerb : "update";
  else { verb = "write"; recognised = false; }
  if (["create", "update", "write"].includes(verb) && words.some(w => MONEY.has(w) || MONEY.has(singular(w)))) verb = "pay";
  let resource = segs.filter(s => !["users", "me", "api", "rest", "graphql", "v1", "v2", "v3"].includes(s.toLowerCase()));
  if (pathWord && resource.length && tokens(resource[resource.length - 1]).includes(pathWord) && !looksLikeId(resource[resource.length - 1])) resource = resource.slice(0, -1);
  return { system, verb: verb as Verb, target: resource.length ? resource.slice(-2).join("/") : null, source: "url", recognised };
}

function wordVerb(w: string): string | null {
  for (const c of [w, singular(w)]) {
    if (SEARCH.has(c)) return "search";
    if (c in VERB_MAP) return VERB_MAP[c];
  }
  return null;
}

export function detectFunctionName(name: string): Detection {
  const toks = tokens(name);
  const [system, rest] = splitSystem(toks);
  const [verb, recognised] = classify(rest);
  return { system, verb, target: nouns(rest.filter(t => !["users", "me", "api", "v1", "v2", "v3"].includes(t))), source: "heuristic", recognised };
}

export function detect(opts: { system?: string | null; verb?: Verb | null; target?: string | null; toolName?: string | null;
  server?: string | null; method?: string | null; url?: string | null; functionName?: string | null }): Detection {
  const key = opts.toolName ?? (opts.url ? `${(opts.method ?? "GET").toUpperCase()} ${opts.url}` : null) ?? opts.functionName;
  if (key && overrides.has(key)) { const o = overrides.get(key)!; return { system: opts.system ?? o.system, verb: opts.verb ?? o.verb, target: opts.target ?? null, source: "manual", recognised: true }; }
  let d: Detection = { system: "unknown", verb: "write", target: null, source: "heuristic", recognised: false };
  if (opts.toolName) d = detectToolName(opts.toolName, opts.server);
  else if (opts.url) d = detectUrl(opts.method ?? "GET", opts.url);
  else if (opts.functionName) d = detectFunctionName(opts.functionName);
  const system = canonicalSystem(opts.system) ?? opts.system ?? d.system;
  const verb = opts.verb ?? d.verb;
  return { system, verb, target: opts.target ?? d.target, source: opts.system && opts.verb ? "manual" : d.source, recognised: d.recognised || !!opts.verb };
}
