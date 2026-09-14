"use client";
import { useCallback, useEffect, useState } from "react";
import { api, loadConfig, type Entry } from "@/lib/api";

type Stats = { total: number; by_level: Record<string, number>; by_decision: Record<string, number> };

export default function LedgerPage() {
  const [rows, setRows] = useState<Entry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [chain, setChain] = useState<{ ok: boolean; checked: number; broken_at?: number | null } | null>(null);
  const [sel, setSel] = useState<Entry | null>(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState({ run_id: "", agent: "", level: "" });

  const load = useCallback(async () => {
    setErr("");
    try {
      const q = new URLSearchParams({ limit: "100" });
      Object.entries(filter).forEach(([k, v]) => v && q.set(k, v));
      const [r, s, c] = await Promise.all([api<Entry[]>(`/v1/ledger?${q}`), api<Stats>("/v1/ledger/stats"), api<typeof chain>("/v1/ledger/verify")]);
      setRows(r); setStats(s); setChain(c);
    } catch (e) { setErr(String(e)); }
  }, [filter]);

  useEffect(() => { if (loadConfig().key) load(); else setErr("Set the cloud URL and API key in Settings."); }, [load]);

  return (
    <>
      <h1>Ledger</h1>
      {err && <p className="err">{err}</p>}
      {stats && (
        <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
          <div className="card"><div className="muted">actions</div><div className="stat">{stats.total}</div></div>
          <div className="card"><div className="muted">verified</div><div className="stat">{(stats.by_level["verified"] || 0) + (stats.by_level["verified-custom"] || 0)}</div></div>
          <div className="card"><div className="muted">unverified</div><div className="stat" style={{ color: stats.by_level["unverified"] ? "var(--bad)" : undefined }}>{stats.by_level["unverified"] || 0}</div></div>
          <div className="card"><div className="muted">hash chain</div><div className="stat" style={{ color: chain?.ok ? "var(--ok)" : "var(--bad)" }}>{chain ? (chain.ok ? `intact · ${chain.checked}` : `BROKEN at ${chain.broken_at}`) : "…"}</div></div>
        </div>
      )}
      <div className="card" style={{ display: "flex", gap: ".75rem", alignItems: "end" }}>
        <div style={{ flex: 1 }}><label>run id</label><input value={filter.run_id} onChange={e => setFilter({ ...filter, run_id: e.target.value })} /></div>
        <div style={{ flex: 1 }}><label>agent</label><input value={filter.agent} onChange={e => setFilter({ ...filter, agent: e.target.value })} /></div>
        <div style={{ flex: 1 }}><label>level</label>
          <select value={filter.level} onChange={e => setFilter({ ...filter, level: e.target.value })}>
            <option value="">any</option>{["verified", "verified-custom", "acknowledged", "attested-only", "unverified"].map(l => <option key={l}>{l}</option>)}
          </select></div>
        <button className="primary" onClick={load}>Apply</button>
        <a href={`${loadConfig().url}/v1/export?format=csv`} onClick={e => { e.preventDefault(); download("csv"); }}>export CSV</a>
        <a href="#" onClick={e => { e.preventDefault(); download("json"); }}>export JSON</a>
        <a href="#" onClick={e => { e.preventDefault(); download("ietf"); }}>IETF audit trail</a>
        <a href="#" onClick={e => { e.preventDefault(); download("eu-ai-act"); }}>EU AI Act pack</a>
        <button onClick={checkpoint}>Checkpoint now</button>
      </div>
      <table>
        <thead><tr><th>#</th><th>when</th><th>action</th><th>target</th><th>agent / actor</th><th>decision</th><th>confirm</th><th>level</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.seq} className="row" onClick={() => setSel(r)}>
              <td>{r.seq}</td>
              <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
              <td><code>{r.descriptor.system}.{r.descriptor.verb}</code></td>
              <td><code>{r.descriptor.target || "-"}</code> <span className="muted">{r.target_class}</span></td>
              <td>{r.agent || "-"}<br /><span className="muted">{r.actor || ""}</span></td>
              <td><span className={`pill ${r.decision}`}>{r.decision}</span> <span className="muted">{r.risk_tier}</span></td>
              <td><span className={`pill ${r.confirm.status}`}>{r.confirm.status}</span>{r.confirm.approver && <><br /><span className="muted">{r.confirm.approver}</span></>}</td>
              <td><span className={`pill ${r.verification.level}`}>{r.verification.level}</span></td>
            </tr>
          ))}
          {!rows.length && !err && <tr><td colSpan={8} className="muted">No entries yet.</td></tr>}
        </tbody>
      </table>
      {sel && <Drawer e={sel} onClose={() => setSel(null)} />}
    </>
  );

  async function checkpoint() {
    try {
      const c = await api<{ seq: number; signature?: string | null }>("/v1/ledger/checkpoint", { method: "POST" });
      alert(`checkpoint at #${c.seq}${c.signature ? " (signed)" : " (unsigned — set ATTEST_SIGNING_KEY)"}`);
      load();
    } catch (e) { setErr(String(e)); }
  }

  async function download(fmt: string) {
    const { url, key } = loadConfig();
    const res = await fetch(`${url}/v1/export?format=${fmt}`, { headers: { Authorization: `Bearer ${key}` } });
    const blob = await res.blob();
    const ext = fmt === "ietf" ? "jsonl" : fmt === "eu-ai-act" ? "eu-ai-act.json" : fmt;
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `attest-ledger.${ext}`; a.click();
  }
}

function Drawer({ e, onClose }: { e: Entry; onClose: () => void }) {
  return (
    <div className="drawer">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>#{e.seq} <code>{e.descriptor.system}.{e.descriptor.verb}</code></h1>
        <button onClick={onClose}>close</button>
      </div>
      <p className="muted">action <code>{e.action_id}</code> · run <code>{e.run_id || "-"}</code> · source {e.descriptor.source}{e.resumed_from && <> · resumed from <code>{e.resumed_from}</code></>}</p>
      <div className="card">
        <b>Decision trail</b>
        <div><span className={`pill ${e.decision}`}>{e.decision}</span> risk <b>{e.risk_tier}</b> · target <b>{e.target_class}</b> · rules {e.rules_fired.join(", ") || "-"}</div>
        <ul>{e.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        <div>confirm: <span className={`pill ${e.confirm.status}`}>{e.confirm.status}</span> {e.confirm.approver && <>by <b>{e.confirm.approver}</b> via {e.confirm.channel} at {e.confirm.decided_at && new Date(e.confirm.decided_at).toLocaleString()}</>}</div>
        {e.confirm.edits && <pre>edits: {JSON.stringify(e.confirm.edits, null, 1)}</pre>}
      </div>
      <div className="card">
        <b>Params</b> <span className="muted">hash {e.descriptor.params_hash} (raw params never leave the agent)</span>
        <pre>{JSON.stringify(e.params_preview ?? {}, null, 1)}</pre>
      </div>
      <div className="card">
        <b>Execution</b> {e.execution ? <><span className={`pill ${e.execution.status}`}>{e.execution.status}</span> {e.execution.duration_ms != null && <span className="muted">{e.execution.duration_ms} ms</span>}{e.execution.error && <pre className="err">{e.execution.error}</pre>}<pre>{JSON.stringify(e.execution.result_preview ?? null, null, 1)}</pre></> : <span className="muted">did not run</span>}
      </div>
      <div className="card">
        <b>Verification</b> <span className={`pill ${e.verification.level}`}>{e.verification.level}</span> <span className="muted">{e.verification.method}</span>
        <pre>{JSON.stringify(e.verification.evidence, null, 1)}</pre>
      </div>
      <p className="muted">hash <code>{e.hash}</code></p>
    </div>
  );
}
