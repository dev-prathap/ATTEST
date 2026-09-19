"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, RefreshCw, X } from "lucide-react";

import { ConnectionGate, EmptyState } from "@/components/connection-gate";
import { LevelBadge } from "@/components/level-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, loadConfig, type Pending } from "@/lib/api";
import { toast } from "sonner";

export default function InboxPage() {
  const [items, setItems] = useState<Pending[]>([]);
  const [recent, setRecent] = useState<Pending[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [connected, setConnected] = useState<boolean | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const [p, r] = await Promise.all([
        api<Pending[]>("/v1/confirm?status=pending"),
        api<Pending[]>("/v1/confirm?status=all&limit=20"),
      ]);
      setItems(p);
      setRecent(r.filter((x) => x.status !== "pending"));
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    const ok = Boolean(loadConfig().key);
    setConnected(ok);
    if (!ok) return;
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  if (connected === false) return <ConnectionGate />;

  async function decide(id: string, status: "approved" | "rejected") {
    let parsed: unknown = null;
    const raw = (edits[id] || "").trim();
    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch {
        toast.error("Edits must be valid JSON");
        return;
      }
    }
    try {
      await api(`/v1/confirm/${id}/decide`, { method: "POST", body: JSON.stringify({ status, edits: parsed }) });
      toast.success(status === "approved" ? "Approved — the agent resumes with these params" : "Rejected — the action will not run");
      load();
    } catch (e) {
      toast.error("Could not record the decision", { description: String(e) });
    }
  }

  return (
    <>
      <div className="mb-5 flex items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Confirm inbox</h1>
        {items.length > 0 && (
          <span className="rounded-full bg-pending/15 px-2 py-0.5 text-xs font-medium text-pending">{items.length} waiting</span>
        )}
        <Button variant="ghost" size="sm" onClick={load} className="ml-auto text-muted-foreground">
          <RefreshCw className="size-3.5" /> Refresh
        </Button>
      </div>

      {err && <p className="mb-4 text-sm text-unverified">{err}</p>}

      {!items.length && !err && (
        <div className="rounded-lg border">
          <EmptyState
            title="Nothing waiting on a human"
            hint="Requests land here when policy says ask — high risk verbs, external recipients, or params the agent could not fill in. This page refreshes every few seconds."
          />
        </div>
      )}

      <div className="space-y-4">
        {items.map((x) => {
          const hasEdits = Boolean((edits[x.id] || "").trim());
          return (
            <Card key={x.id} id={x.id} className="gap-4">
              <CardHeader className="gap-2">
                <CardTitle className="flex flex-wrap items-center gap-2 font-mono text-sm">
                  {x.descriptor.system}.{x.descriptor.verb}
                  <span className="text-muted-foreground">→</span>
                  {x.descriptor.target || "—"}
                  <LevelBadge value={x.risk_tier === "low" ? undefined : "ask"} />
                  <span className="text-xs font-normal text-muted-foreground">{x.risk_tier} risk · target {x.descriptor.target_class}</span>
                  <span className="ml-auto text-xs font-normal text-muted-foreground">
                    {new Date(x.requested_at).toLocaleString()} · via {x.channel}
                  </span>
                </CardTitle>
                <p className="text-xs text-muted-foreground">
                  agent {x.descriptor.agent || "—"} · actor {x.descriptor.actor || "—"} · run {x.descriptor.run_id || "—"}
                  {x.approvers?.length ? ` · approvers ${x.approvers.join(", ")}` : ""}
                </p>
              </CardHeader>

              <CardContent className="space-y-3">
                <ul className="ml-4 list-disc space-y-0.5 text-sm text-muted-foreground">
                  {x.reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>

                {x.hold && (
                  <p className="flex items-start gap-2 rounded-md border border-pending/40 bg-pending/10 p-2.5 text-sm text-pending">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                    The agent left placeholders it could not fill. Supply the real values below before approving.
                  </p>
                )}

                <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
                  {JSON.stringify(x.descriptor.params, null, 1)}
                </pre>

                <div className="space-y-1.5">
                  <Label htmlFor={`edits-${x.id}`} className="text-xs text-muted-foreground">
                    Edits — JSON merged over the params above
                  </Label>
                  <Textarea
                    id={`edits-${x.id}`}
                    className="min-h-16 font-mono text-xs"
                    value={edits[x.id] || ""}
                    onChange={(e) => setEdits({ ...edits, [x.id]: e.target.value })}
                    placeholder={'{"subject": "…"}'}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={() => decide(x.id, "approved")}>
                    <Check className="size-3.5" /> {hasEdits ? "Approve with edits" : "Approve"}
                  </Button>
                  <Button variant="outline" className="border-unverified/40 text-unverified hover:bg-unverified/10 hover:text-unverified" onClick={() => decide(x.id, "rejected")}>
                    <X className="size-3.5" /> Reject
                  </Button>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">{x.id}</span>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {recent.length > 0 && (
        <>
          <Separator className="my-8" />
          <h2 className="mb-3 text-sm font-semibold">Recent decisions</h2>
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-44">When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Approver</TableHead>
                  <TableHead>Channel</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.map((x) => (
                  <TableRow key={x.id}>
                    <TableCell className="text-muted-foreground">{new Date(x.requested_at).toLocaleString()}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {x.descriptor.system}.{x.descriptor.verb} <span className="text-muted-foreground">→</span> {x.descriptor.target || "—"}
                    </TableCell>
                    <TableCell><LevelBadge value={x.status} /></TableCell>
                    <TableCell className="text-xs">{x.approver || "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{x.channel}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </>
  );
}
