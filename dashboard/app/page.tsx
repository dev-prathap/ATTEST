"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, FileClock, Link2, RefreshCw, ShieldCheck } from "lucide-react";

import { ConnectionGate, EmptyState } from "@/components/connection-gate";
import { LevelBadge } from "@/components/level-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, loadConfig, type Entry } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

type Stats = { total: number; by_level: Record<string, number>; by_decision: Record<string, number> };
type Chain = { ok: boolean; checked: number; broken_at?: number | null };
const LEVELS = ["verified", "verified-custom", "acknowledged", "attested-only", "unverified"];

export default function LedgerPage() {
  const [rows, setRows] = useState<Entry[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [chain, setChain] = useState<Chain | null>(null);
  const [sel, setSel] = useState<Entry | null>(null);
  const [err, setErr] = useState("");
  const [connected, setConnected] = useState<boolean | null>(null);
  const [filter, setFilter] = useState({ run_id: "", agent: "", level: "" });

  const load = useCallback(async () => {
    setErr("");
    try {
      const q = new URLSearchParams({ limit: "100" });
      Object.entries(filter).forEach(([k, v]) => v && q.set(k, v));
      const [r, s, c] = await Promise.all([
        api<Entry[]>(`/v1/ledger?${q}`),
        api<Stats>("/v1/ledger/stats"),
        api<Chain>("/v1/ledger/verify"),
      ]);
      setRows(r);
      setStats(s);
      setChain(c);
    } catch (e) {
      setErr(String(e));
      setRows([]);
    }
  }, [filter]);

  useEffect(() => {
    const ok = Boolean(loadConfig().key);
    setConnected(ok);
    if (ok) load();
  }, [load]);

  if (connected === false) return <ConnectionGate />;

  const verified = (stats?.by_level["verified"] ?? 0) + (stats?.by_level["verified-custom"] ?? 0);
  const unverified = stats?.by_level["unverified"] ?? 0;

  return (
    <>
      <div className="mb-5 flex items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Ledger</h1>
        <Button variant="ghost" size="sm" onClick={load} className="text-muted-foreground">
          <RefreshCw className="size-3.5" /> Refresh
        </Button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={checkpoint}>
            <ShieldCheck className="size-3.5" /> Checkpoint
          </Button>
          {(["csv", "json", "ietf", "eu-ai-act"] as const).map((f) => (
            <Button key={f} variant="ghost" size="sm" onClick={() => download(f)} className="text-muted-foreground">
              <Download className="size-3.5" /> {f === "eu-ai-act" ? "EU AI Act" : f.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Actions" value={stats?.total} icon={FileClock} />
        <Stat label="Verified" value={verified} icon={CheckCircle2} tone={verified ? "text-verified" : undefined} />
        <Stat
          label="Unverified"
          value={unverified}
          icon={AlertTriangle}
          tone={unverified ? "text-unverified" : undefined}
          hint={unverified ? "a check contradicted the claim" : undefined}
        />
        <Stat
          label="Hash chain"
          value={chain ? (chain.ok ? "intact" : `broken at #${chain.broken_at}`) : undefined}
          icon={Link2}
          tone={chain ? (chain.ok ? "text-verified" : "text-unverified") : undefined}
          hint={chain?.ok ? `${chain.checked} entries` : undefined}
        />
      </div>

      <Card className="mb-5 py-4">
        <CardContent className="flex flex-wrap items-end gap-3">
          <Field label="Run id">
            <Input value={filter.run_id} onChange={(e) => setFilter({ ...filter, run_id: e.target.value })} placeholder="run_…" />
          </Field>
          <Field label="Agent">
            <Input value={filter.agent} onChange={(e) => setFilter({ ...filter, agent: e.target.value })} placeholder="followup-agent@v3" />
          </Field>
          <Field label="Level">
            <Select value={filter.level || "any"} onValueChange={(v) => setFilter({ ...filter, level: v === "any" ? "" : v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any level</SelectItem>
                {LEVELS.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Button onClick={load}>Apply</Button>
        </CardContent>
      </Card>

      {err && <p className="mb-4 text-sm text-unverified">{err}</p>}

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-14">#</TableHead>
              <TableHead className="w-44">When</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Decision</TableHead>
              <TableHead>Confirm</TableHead>
              <TableHead className="text-right">Level</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows === null &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={8}><Skeleton className="h-5 w-full" /></TableCell>
                </TableRow>
              ))}
            {rows?.map((r) => (
              <TableRow
                key={r.seq}
                onClick={() => setSel(r)}
                className={cn("cursor-pointer", r.verification.level === "unverified" && "bg-unverified/5")}
              >
                <TableCell className="text-muted-foreground">{r.seq}</TableCell>
                <TableCell className="text-muted-foreground">{new Date(r.created_at).toLocaleString()}</TableCell>
                <TableCell className="font-mono text-xs">{r.descriptor.system}.{r.descriptor.verb}</TableCell>
                <TableCell className="max-w-56 truncate font-mono text-xs" title={r.descriptor.target ?? ""}>
                  {r.descriptor.target || "—"}
                  <span className="ml-1.5 text-muted-foreground">{r.target_class !== "none" && r.target_class}</span>
                </TableCell>
                <TableCell className="text-xs">{r.agent || "—"}</TableCell>
                <TableCell><LevelBadge value={r.decision} /> <span className="text-xs text-muted-foreground">{r.risk_tier}</span></TableCell>
                <TableCell>
                  <LevelBadge value={r.confirm.status === "not_required" ? undefined : r.confirm.status} />
                  {r.confirm.approver && <div className="text-xs text-muted-foreground">{r.confirm.approver}</div>}
                  {r.confirm.status === "not_required" && <span className="text-xs text-muted-foreground">—</span>}
                </TableCell>
                <TableCell className="text-right"><LevelBadge value={r.verification.level} /></TableCell>
              </TableRow>
            ))}
            {rows?.length === 0 && !err && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={8} className="p-0">
                  <EmptyState
                    title="No actions recorded yet"
                    hint="Wrap a tool with Attest and run your agent. Every action it takes lands here with its decision, approver and verification level."
                  />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Sheet open={Boolean(sel)} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-xl">{sel && <Detail e={sel} />}</SheetContent>
      </Sheet>
    </>
  );

  async function checkpoint() {
    try {
      const c = await api<{ seq: number; signature?: string | null }>("/v1/ledger/checkpoint", { method: "POST" });
      toast.success(`Checkpoint at #${c.seq}`, {
        description: c.signature ? "Signed. Anchor it to make history tamper-evident off-site." : "Unsigned — set ATTEST_SIGNING_KEY on the server.",
      });
      load();
    } catch (e) {
      toast.error("Checkpoint failed", { description: String(e) });
    }
  }

  async function download(fmt: string) {
    const { url, key } = loadConfig();
    try {
      const res = await fetch(`${url}/v1/export?format=${fmt}`, { headers: { Authorization: `Bearer ${key}` } });
      if (!res.ok) throw new Error(`${res.status}: ${(await res.json().catch(() => ({}))).detail ?? res.statusText}`);
      const blob = await res.blob();
      const ext = fmt === "ietf" ? "jsonl" : fmt === "eu-ai-act" ? "eu-ai-act.json" : fmt;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `attest-ledger.${ext}`;
      a.click();
    } catch (e) {
      toast.error("Export failed", { description: String(e) });
    }
  }
}

function Stat({ label, value, icon: Icon, tone, hint }: {
  label: string; value?: number | string; icon: React.ElementType; tone?: string; hint?: string;
}) {
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Icon className="size-3.5" /> {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4">
        {value === undefined ? <Skeleton className="h-7 w-20" /> : <p className={cn("text-2xl font-semibold tabular-nums", tone)}>{value}</p>}
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-44 flex-1 space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Block({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2 py-4">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {note && <span className="text-xs text-muted-foreground">{note}</span>}
      </div>
      {children}
    </section>
  );
}

const Pre = ({ children }: { children: React.ReactNode }) => (
  <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{children}</pre>
);

function Detail({ e }: { e: Entry }) {
  const bad = e.verification.level === "unverified";
  return (
    <>
      <SheetHeader className="gap-1">
        <SheetTitle className="flex items-center gap-2 font-mono text-base">
          #{e.seq} {e.descriptor.system}.{e.descriptor.verb}
          <LevelBadge value={e.verification.level} />
        </SheetTitle>
        <SheetDescription>
          {e.descriptor.target || "no target"} · run {e.run_id || "—"} · detected from {e.descriptor.source}
        </SheetDescription>
      </SheetHeader>

      <div className="divide-y px-4 pb-8">
        {bad && (
          <div className="my-4 rounded-md border border-unverified/40 bg-unverified/10 p-3 text-sm">
            <p className="font-medium text-unverified">The record contradicts what was claimed.</p>
            <p className="mt-1 text-muted-foreground">
              Fields that did not match: {(e.verification.evidence.failed as string[] | undefined)?.join(", ") || "see evidence"}
            </p>
          </div>
        )}

        <Block title="Decision" note={`${e.risk_tier} risk · target ${e.target_class}`}>
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge value={e.decision} />
            {e.rules_fired.map((r) => (
              <span key={r} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{r}</span>
            ))}
          </div>
          <ul className="ml-4 list-disc space-y-0.5 text-sm text-muted-foreground">
            {e.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </Block>

        <Block title="Human confirmation">
          {e.confirm.status === "not_required" ? (
            <p className="text-sm text-muted-foreground">Not required — policy said act.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <LevelBadge value={e.confirm.status} />
                {e.confirm.approver && <span>by <b>{e.confirm.approver}</b></span>}
                {e.confirm.channel && <span className="text-muted-foreground">via {e.confirm.channel}</span>}
                {e.confirm.decided_at && <span className="text-muted-foreground">{new Date(e.confirm.decided_at).toLocaleString()}</span>}
              </div>
              {e.confirm.edits && <Pre>{JSON.stringify(e.confirm.edits, null, 1)}</Pre>}
            </>
          )}
        </Block>

        <Block title="Parameters" note={`hash ${e.descriptor.params_hash} — raw params never leave the agent`}>
          <Pre>{JSON.stringify(e.params_preview ?? {}, null, 1)}</Pre>
        </Block>

        <Block title="Execution">
          {e.execution ? (
            <>
              <div className="flex items-center gap-2 text-sm">
                <LevelBadge value={e.execution.status} />
                {e.execution.duration_ms != null && <span className="text-muted-foreground">{e.execution.duration_ms} ms</span>}
              </div>
              {e.execution.error && <p className="text-sm text-unverified">{e.execution.error}</p>}
              {e.execution.result_preview != null && <Pre>{JSON.stringify(e.execution.result_preview, null, 1)}</Pre>}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Never ran — refused or rejected before execution.</p>
          )}
        </Block>

        <Block title="Verification" note={e.verification.method ?? undefined}>
          <Pre>{JSON.stringify(e.verification.evidence, null, 1)}</Pre>
        </Block>

        <Separator />
        <p className="pt-3 font-mono text-[11px] break-all text-muted-foreground">
          action {e.action_id}
          <br />
          hash {e.hash}
        </p>
      </div>
    </>
  );
}
