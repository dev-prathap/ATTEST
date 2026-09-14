"use client";
import { useEffect, useState } from "react";
import { api, loadConfig, saveConfig } from "@/lib/api";

type Key = { id: string; name: string; role: string; prefix: string; created_at: string; revoked_at?: string | null; api_key?: string };
type Agent = { id: string; name: string; actions: number; last_seen_at?: string | null };

export default function SettingsPage() {
  const [cfg, setCfg] = useState({ url: "", key: "" });
  const [me, setMe] = useState<{ org: { name: string; slug: string; domain?: string }; key: { name: string; role: string } } | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [policy, setPolicy] = useState<{ version: number; yaml: string }>({ version: 0, yaml: "" });
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [newKey, setNewKey] = useState({ name: "", role: "agent" });
  const [created, setCreated] = useState<Key | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { setCfg(loadConfig()); }, []);

  async function connect() {
    saveConfig(cfg); setMsg("");
    try {
      const m = await api<typeof me>("/v1/me"); setMe(m);
      const [k, a, p] = await Promise.all([api<Key[]>("/v1/keys").catch(() => []), api<Agent[]>("/v1/agents"), api<typeof policy>("/v1/policy")]);
      setKeys(k); setAgents(a); setPolicy(p);
      if (m?.key.role === "admin") setSettings(await api("/v1/settings"));
    } catch (e) { setMsg(String(e)); setMe(null); }
  }

  async function createKey() {
    try { const k = await api<Key>("/v1/keys", { method: "POST", body: JSON.stringify(newKey) }); setCreated(k); setKeys([...keys, k]); }
    catch (e) { setMsg(String(e)); }
  }
  async function revoke(id: string) {
    try { await api(`/v1/keys/${id}`, { method: "DELETE" }); setKeys(keys.map(k => k.id === id ? { ...k, revoked_at: "now" } : k)); } catch (e) { setMsg(String(e)); }
  }
  async function savePolicy() {
    try { const r = await api<{ version: number; rules: number }>("/v1/policy", { method: "PUT", body: JSON.stringify({ yaml: policy.yaml }) }); setPolicy({ ...policy, version: r.version }); setMsg(`policy v${r.version} saved (${r.rules} rules)`); }
    catch (e) { setMsg(String(e)); }
  }
  async function saveSettings() {
    const body = Object.fromEntries(Object.entries(settings).filter(([, v]) => v && !String(v).endsWith("…")));
    try { setSettings(await api("/v1/settings", { method: "PUT", body: JSON.stringify(body) })); setMsg("settings saved"); } catch (e) { setMsg(String(e)); }
  }

  const field = (k: string, label: string, secret = false) => (
    <div><label>{label}</label><input type={secret ? "password" : "text"} value={settings[k] || ""} onChange={e => setSettings({ ...settings, [k]: e.target.value })} placeholder={secret ? "unchanged" : ""} /></div>
  );

  return (
    <>
      <h1>Settings</h1>
      {msg && <p className={msg.includes("Error") || /^\d{3}:/.test(msg) ? "err" : "muted"}>{msg}</p>}
      <div className="card">
        <b>Connection</b>
        <div className="grid">
          <div><label>Attest Cloud URL</label><input value={cfg.url} onChange={e => setCfg({ ...cfg, url: e.target.value })} /></div>
          <div><label>API key</label><input type="password" value={cfg.key} onChange={e => setCfg({ ...cfg, key: e.target.value })} /></div>
        </div>
        <div style={{ marginTop: ".6rem" }}><button className="primary" onClick={connect}>Connect</button> {me && <span className="muted">org <b>{me.org.name}</b> ({me.org.slug}) · key {me.key.name} · role {me.key.role}</span>}</div>
      </div>
      {me && (
        <>
          <div className="card">
            <b>Policy</b> <span className="muted">v{policy.version} · first match wins · built-in rules R0–R4 run first</span>
            <textarea value={policy.yaml} onChange={e => setPolicy({ ...policy, yaml: e.target.value })} style={{ minHeight: "14rem" }} />
            <button className="primary" onClick={savePolicy} disabled={me.key.role !== "admin"}>Save as new version</button>
          </div>
          <div className="grid">
            <div className="card">
              <b>Agents</b>
              <table><thead><tr><th>name</th><th>actions</th><th>last seen</th></tr></thead>
                <tbody>{agents.map(a => <tr key={a.id}><td>{a.name}</td><td>{a.actions}</td><td className="muted">{a.last_seen_at ? new Date(a.last_seen_at).toLocaleString() : "-"}</td></tr>)}
                  {!agents.length && <tr><td colSpan={3} className="muted">Agents appear after their first attested action.</td></tr>}</tbody></table>
            </div>
            <div className="card">
              <b>API keys</b>
              <table><thead><tr><th>name</th><th>role</th><th>prefix</th><th></th></tr></thead>
                <tbody>{keys.map(k => <tr key={k.id}><td>{k.name}</td><td>{k.role}</td><td><code>{k.prefix}…</code></td>
                  <td>{k.revoked_at ? <span className="muted">revoked</span> : <button className="danger" onClick={() => revoke(k.id)}>revoke</button>}</td></tr>)}</tbody></table>
              {me.key.role === "admin" && (
                <div style={{ display: "flex", gap: ".5rem", alignItems: "end", marginTop: ".6rem" }}>
                  <div style={{ flex: 1 }}><label>name</label><input value={newKey.name} onChange={e => setNewKey({ ...newKey, name: e.target.value })} /></div>
                  <div><label>role</label><select value={newKey.role} onChange={e => setNewKey({ ...newKey, role: e.target.value })}><option>agent</option><option>approver</option><option>admin</option></select></div>
                  <button className="primary" onClick={createKey}>Create</button>
                </div>
              )}
              {created?.api_key && <pre>new key (shown once): {created.api_key}</pre>}
            </div>
          </div>
          {me.key.role === "admin" && (
            <div className="card">
              <b>Org settings</b> <span className="muted">confirm channels the cloud notifies; tokens are stored server-side and masked here</span>
              <div className="grid">
                {field("domain", "Organisation email domain (recipients here are internal)")}
                {field("inbox_url", "Dashboard URL (linked from Slack cards)")}
                {field("slack_channel", "Slack channel for confirm cards")}
                {field("slack_bot_token", "Slack bot token (xoxb-…)", true)}
                {field("slack_signing_secret", "Slack signing secret", true)}
                {field("webhook_url", "Webhook URL for confirm requests")}
                {field("webhook_secret", "Webhook signing secret", true)}
              </div>
              <button className="primary" onClick={saveSettings} style={{ marginTop: ".6rem" }}>Save</button>
            </div>
          )}
        </>
      )}
    </>
  );
}
