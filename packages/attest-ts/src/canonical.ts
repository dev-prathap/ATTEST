/** Canonical JSON identical to the Python SDK (`json.dumps(sort_keys=True, separators=(",",":"))` with
 *  ensure_ascii), so hashes match across SDKs and cloud. */
import { createHash } from "node:crypto";

export function canonicalJson(value: unknown): string {
  return encode(value);
}

function encode(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : JSON.stringify(v);
  if (typeof v === "string") return str(v);
  if (Array.isArray(v)) return "[" + v.map(encode).join(",") + "]";
  if (v instanceof Date) return str(v.toISOString().replace("T", " ").replace("Z", "+00:00"));
  if (typeof v === "object") {
    const keys = Object.keys(v as object).sort();
    return "{" + keys.map(k => str(k) + ":" + encode((v as Record<string, unknown>)[k])).join(",") + "}";
  }
  return str(String(v));
}

function str(s: string): string {
  let out = '"';
  for (const ch of s) {
    const c = ch.codePointAt(0)!;
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20) out += "\\u" + c.toString(16).padStart(4, "0");
    else if (c > 0x7e) {
      if (c > 0xffff) { // surrogate pair, as Python does
        const hi = Math.floor((c - 0x10000) / 0x400) + 0xd800, lo = ((c - 0x10000) % 0x400) + 0xdc00;
        out += "\\u" + hi.toString(16).padStart(4, "0") + "\\u" + lo.toString(16).padStart(4, "0");
      } else out += "\\u" + c.toString(16).padStart(4, "0");
    } else out += ch;
  }
  return out + '"';
}

export function sha256(data: string | Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

export function shortHash(value: unknown): string {
  return sha256(canonicalJson(value)).slice(0, 16);
}

export function newId(prefix = "act"): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(10))).map(b => b.toString(16).padStart(2, "0")).join("");
  return `${prefix}_${hex}`;
}
