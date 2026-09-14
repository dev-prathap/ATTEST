"use client";

export type Config = { url: string; key: string };

export function loadConfig(): Config {
  if (typeof window === "undefined") return { url: "", key: "" };
  return {
    url: localStorage.getItem("attest.url") || process.env.NEXT_PUBLIC_ATTEST_CLOUD_URL || "http://127.0.0.1:8400",
    key: localStorage.getItem("attest.key") || "",
  };
}

export function saveConfig(c: Config) {
  localStorage.setItem("attest.url", c.url.replace(/\/$/, ""));
  localStorage.setItem("attest.key", c.key);
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const { url, key } = loadConfig();
  const res = await fetch(url + path, {
    ...init,
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export type Entry = {
  seq: number; hash: string; id: string; action_id: string; run_id?: string; agent?: string; actor?: string;
  decision: string; risk_tier: string; reasons: string[]; rules_fired: string[]; target_class: string;
  descriptor: { system: string; verb: string; target?: string; params_hash: string; source: string; extra?: Record<string, unknown> };
  params_preview?: Record<string, unknown>;
  confirm: { status: string; channel?: string; approver?: string; decided_at?: string; edits?: Record<string, unknown> };
  execution?: { status: string; error?: string; duration_ms?: number; result_preview?: unknown };
  verification: { level: string; method?: string; matched?: boolean | null; evidence: Record<string, unknown> };
  created_at: string; resumed_from?: string;
};

export type Pending = {
  id: string; resume_token: string; status: string; risk_tier: string; reasons: string[]; approvers: string[]; hold: boolean;
  requested_at: string; channel?: string; approver?: string;
  descriptor: { system: string; verb: string; target?: string; target_class: string; params: Record<string, unknown>; agent?: string; actor?: string; run_id?: string };
};
