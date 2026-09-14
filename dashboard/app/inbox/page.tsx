"use client";
import { useCallback, useEffect, useState } from "react";
import { api, loadConfig, type Pending } from "@/lib/api";

export default function InboxPage() {
  const [items, setItems] = useState<Pending[]>([]);
  const [recent, setRecent] = useState<Pending[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const [p, r] = await Promise.all([api<Pending[]>("/v1/confirm?status=pending"), api<Pending[]>("/v1/confirm?status=all&limit=20")]);
      setItems(p); setRecent(r.filter(x => x.status !== "pending"));
    } catch (e) { setErr(String(e)); }
  }, []);

  useEffect(() => {
    if (!loadConfig().key) { setErr("Set the cloud URL and API key in Settings."); return; }
    load(); const t = setInterval(load, 4000); return () => clearInterval(t);
  }, [load]);

  async function decide(id: string, status: "approved" | "rejected") {
    let parsed: unknown = null;
    const raw = (edits[id] || "").trim();
    if (raw) { try { parsed = JSON.parse(raw); } catch { setErr("edits must be JSON"); return; } }
    try {
      await api(`/v1/confirm/${id}/decide`, { method: "POST", body: JSON.stringify({ status, edits: parsed }) });
      load();
    } catch (e) { setErr(String(e)); }
  }

  return (
    <>
      <h1>Confirm inbox</h1>
      {err && <p className="err">{err}</p>}
      {!items.length && !err && <p className="muted">Nothing pending.</p>}
      {items.map(x => (
        <div className="card" key={x.id} id={x.id}>
          <div style={{ display: "flex", gap: ".75rem", alignItems: "baseline" }}>
            <b><code>{x.descriptor.system}.{x.descriptor.verb}</code></b> → <code>{x.descriptor.target || "-"}</code>
            <span className={`pill ${x.risk_tier === "low" ? "" : "ask"}`}>{x.risk_tier}</span>
            <span className="muted">target {x.descriptor.target_class}</span>
            <span className="muted" style={{ marginLeft: "auto" }}>{new Date(x.requested_at).toLocaleString()} · via {x.channel}</span>
          </div>
          <div className="muted">agent {x.descriptor.agent || "-"} · actor {x.descriptor.actor || "-"} · run {x.descriptor.run_id || "-"}{x.approvers?.length ? ` · approvers: ${x.approvers.join(", ")}` : ""}</div>
          <ul>{x.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          {x.hold && <p className="err">Needs input fixed before it can proceed (placeholders). Edit the params below.</p>}
          <pre>{JSON.stringify(x.descriptor.params, null, 1)}</pre>
          <label>edits (JSON, merged over params)</label>
          <textarea value={edits[x.id] || ""} onChange={e => setEdits({ ...edits, [x.id]: e.target.value })} placeholder='{"subject": "..."}' style={{ minHeight: "3.5rem" }} />
          <div style={{ display: "flex", gap: ".5rem", marginTop: ".5rem" }}>
            <button className="primary" onClick={() => decide(x.id, "approved")}>{(edits[x.id] || "").trim() ? "Approve with edits" : "Approve"}</button>
            <button className="danger" onClick={() => decide(x.id, "rejected")}>Reject</button>
            <span className="muted" style={{ marginLeft: "auto" }}>request {x.id}</span>
          </div>
        </div>
      ))}
      {recent.length > 0 && (
        <>
          <h1 style={{ marginTop: "2rem" }}>Recent decisions</h1>
          <table>
            <thead><tr><th>when</th><th>action</th><th>status</th><th>approver</th><th>channel</th></tr></thead>
            <tbody>{recent.map(x => (
              <tr key={x.id}><td className="muted">{new Date(x.requested_at).toLocaleString()}</td><td><code>{x.descriptor.system}.{x.descriptor.verb}</code> → <code>{x.descriptor.target || "-"}</code></td>
                <td><span className={`pill ${x.status}`}>{x.status}</span></td><td>{x.approver || "-"}</td><td className="muted">{x.channel}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
    </>
  );
}
