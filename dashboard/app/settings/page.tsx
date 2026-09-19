"use client";

import { useEffect, useState } from "react";
import { Copy, Plug, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, loadConfig, saveConfig } from "@/lib/api";
import { toast } from "sonner";

type Key = { id: string; name: string; role: string; prefix: string; created_at: string; revoked_at?: string | null; api_key?: string };
type Agent = { id: string; name: string; actions: number; last_seen_at?: string | null };
type Me = { org: { name: string; slug: string; domain?: string }; key: { name: string; role: string } };

const ORG_FIELDS: [string, string, boolean?][] = [
  ["domain", "Organisation email domain — recipients here count as internal"],
  ["inbox_url", "Dashboard URL linked from Slack cards"],
  ["slack_channel", "Slack channel for confirm cards"],
  ["slack_bot_token", "Slack bot token (xoxb-…)", true],
  ["slack_signing_secret", "Slack signing secret", true],
  ["webhook_url", "Webhook URL for confirm requests"],
  ["webhook_secret", "Webhook signing secret", true],
  ["retention_days", "Retention in days — older rows are pruned behind a signed checkpoint"],
];

export default function SettingsPage() {
  const [cfg, setCfg] = useState({ url: "", key: "" });
  const [me, setMe] = useState<Me | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [policy, setPolicy] = useState<{ version: number; yaml: string }>({ version: 0, yaml: "" });
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [newKey, setNewKey] = useState({ name: "", role: "agent" });
  const [created, setCreated] = useState<Key | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setCfg(loadConfig()); }, []);

  const admin = me?.key.role === "admin";

  async function connect() {
    saveConfig(cfg);
    setBusy(true);
    try {
      const m = await api<Me>("/v1/me");
      setMe(m);
      const [k, a, p] = await Promise.all([
        api<Key[]>("/v1/keys").catch(() => [] as Key[]),
        api<Agent[]>("/v1/agents"),
        api<{ version: number; yaml: string }>("/v1/policy"),
      ]);
      setKeys(k); setAgents(a); setPolicy(p);
      if (m.key.role === "admin") setSettings(await api("/v1/settings"));
      toast.success(`Connected to ${m.org.name}`, { description: `key ${m.key.name} · role ${m.key.role}` });
    } catch (e) {
      setMe(null);
      toast.error("Could not connect", { description: String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function createKey() {
    try {
      const k = await api<Key>("/v1/keys", { method: "POST", body: JSON.stringify(newKey) });
      setCreated(k);
      setKeys([...keys, k]);
      setNewKey({ name: "", role: "agent" });
    } catch (e) {
      toast.error("Could not create the key", { description: String(e) });
    }
  }

  async function revoke(id: string) {
    try {
      await api(`/v1/keys/${id}`, { method: "DELETE" });
      setKeys(keys.map((k) => (k.id === id ? { ...k, revoked_at: "now" } : k)));
      toast.success("Key revoked");
    } catch (e) {
      toast.error("Could not revoke the key", { description: String(e) });
    }
  }

  async function savePolicy() {
    try {
      const r = await api<{ version: number; rules: number }>("/v1/policy", { method: "PUT", body: JSON.stringify({ yaml: policy.yaml }) });
      setPolicy({ ...policy, version: r.version });
      toast.success(`Policy v${r.version} saved`, { description: `${r.rules} rules · applies to the next action` });
    } catch (e) {
      toast.error("Policy rejected", { description: String(e) });
    }
  }

  async function saveSettings() {
    const body: Record<string, unknown> = Object.fromEntries(
      Object.entries(settings).filter(([, v]) => v && !String(v).endsWith("…")),
    );
    if (body.retention_days) body.retention_days = Number(body.retention_days);
    try {
      setSettings(await api("/v1/settings", { method: "PUT", body: JSON.stringify(body) }));
      toast.success("Org settings saved");
    } catch (e) {
      toast.error("Could not save settings", { description: String(e) });
    }
  }

  return (
    <>
      <h1 className="mb-5 text-xl font-semibold tracking-tight">Settings</h1>

      <Card className="mb-5">
        <CardHeader>
          <CardTitle className="text-base">Connection</CardTitle>
          <CardDescription>
            Stored in this browser only. The key decides what you can see and change.
            {me && <> Connected to <b>{me.org.name}</b> ({me.org.slug}) as {me.key.name}, role {me.key.role}.</>}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="url">Attest Cloud URL</Label>
              <Input id="url" value={cfg.url} onChange={(e) => setCfg({ ...cfg, url: e.target.value })} placeholder="https://cloud.example.com" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="key">API key</Label>
              <Input id="key" type="password" value={cfg.key} onChange={(e) => setCfg({ ...cfg, key: e.target.value })} placeholder="att_…" />
            </div>
          </div>
          <Button onClick={connect} disabled={busy}>
            <Plug className="size-3.5" /> {busy ? "Connecting…" : "Connect"}
          </Button>
        </CardContent>
      </Card>

      {me && (
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Policy — version {policy.version}</CardTitle>
              <CardDescription>
                First match wins. Built-in rules R0 to R4 run first, then your YAML. Use groups for approver lists and agents for per-agent overrides.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea
                className="min-h-56 font-mono text-xs"
                value={policy.yaml}
                onChange={(e) => setPolicy({ ...policy, yaml: e.target.value })}
                spellCheck={false}
              />
              <Button onClick={savePolicy} disabled={!admin}>Save as new version</Button>
              {!admin && <p className="text-xs text-muted-foreground">Read only — an admin key can save a new version.</p>}
            </CardContent>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card className="gap-4">
              <CardHeader>
                <CardTitle className="text-base">Agents</CardTitle>
                <CardDescription>Registered by their first attested action.</CardDescription>
              </CardHeader>
              <CardContent className="px-0">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-6">Name</TableHead>
                      <TableHead>Actions</TableHead>
                      <TableHead className="pr-6">Last seen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {agents.map((a) => (
                      <TableRow key={a.id}>
                        <TableCell className="pl-6 font-mono text-xs">{a.name}</TableCell>
                        <TableCell className="tabular-nums">{a.actions}</TableCell>
                        <TableCell className="pr-6 text-xs text-muted-foreground">
                          {a.last_seen_at ? new Date(a.last_seen_at).toLocaleString() : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                    {!agents.length && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={3} className="px-6 py-6 text-sm text-muted-foreground">
                          No agents yet. One appears here after its first attested action.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card className="gap-4">
              <CardHeader>
                <CardTitle className="text-base">API keys</CardTitle>
                <CardDescription>Agent keys write actions. Approver keys decide. Admin keys change policy.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 px-0">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="pl-6">Name</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Prefix</TableHead>
                      <TableHead className="pr-6" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {keys.map((k) => (
                      <TableRow key={k.id}>
                        <TableCell className="pl-6">{k.name}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{k.role}</TableCell>
                        <TableCell className="font-mono text-xs">{k.prefix}…</TableCell>
                        <TableCell className="pr-6 text-right">
                          {k.revoked_at ? (
                            <span className="text-xs text-muted-foreground">revoked</span>
                          ) : (
                            <Button variant="ghost" size="sm" className="text-unverified hover:bg-unverified/10 hover:text-unverified" onClick={() => revoke(k.id)}>
                              Revoke
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                    {!keys.length && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={4} className="px-6 py-6 text-sm text-muted-foreground">
                          No keys visible to this key.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>

                {admin && (
                  <div className="flex flex-wrap items-end gap-2 px-6">
                    <div className="min-w-40 flex-1 space-y-1.5">
                      <Label htmlFor="keyname" className="text-xs text-muted-foreground">Name</Label>
                      <Input id="keyname" value={newKey.name} onChange={(e) => setNewKey({ ...newKey, name: e.target.value })} placeholder="followup-agent" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">Role</Label>
                      <Select value={newKey.role} onValueChange={(v) => setNewKey({ ...newKey, role: v })}>
                        <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="agent">agent</SelectItem>
                          <SelectItem value="approver">approver</SelectItem>
                          <SelectItem value="admin">admin</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <Button onClick={createKey} disabled={!newKey.name.trim()}>
                      <Plus className="size-3.5" /> Create
                    </Button>
                  </div>
                )}

                {created?.api_key && (
                  <div className="mx-6 rounded-md border border-pending/40 bg-pending/10 p-3">
                    <p className="text-xs font-medium text-pending">Copy this now — it is never shown again.</p>
                    <div className="mt-1.5 flex items-center gap-2">
                      <code className="flex-1 break-all font-mono text-xs">{created.api_key}</code>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          navigator.clipboard.writeText(created.api_key!);
                          toast.success("Key copied");
                        }}
                      >
                        <Copy className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {admin && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Org settings</CardTitle>
                <CardDescription>Where the cloud sends confirm requests. Secrets are stored server-side and shown masked.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  {ORG_FIELDS.map(([k, label, secret]) => (
                    <div key={k} className="space-y-1.5">
                      <Label htmlFor={k} className="text-xs text-muted-foreground">{label}</Label>
                      <Input
                        id={k}
                        type={secret ? "password" : "text"}
                        value={settings[k] || ""}
                        onChange={(e) => setSettings({ ...settings, [k]: e.target.value })}
                        placeholder={secret ? "unchanged" : ""}
                      />
                    </div>
                  ))}
                </div>
                <Button onClick={saveSettings}>Save</Button>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
