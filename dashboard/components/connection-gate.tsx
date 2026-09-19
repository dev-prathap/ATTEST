"use client";

import Link from "next/link";
import { KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Shown instead of a page when no cloud URL + key are stored yet. */
export function ConnectionGate() {
  return (
    <Card className="mx-auto mt-16 max-w-md">
      <CardHeader>
        <div className="mb-2 flex size-9 items-center justify-center rounded-md border bg-muted">
          <KeyRound className="size-4 text-muted-foreground" />
        </div>
        <CardTitle>Connect to Attest Cloud</CardTitle>
        <CardDescription>
          This dashboard talks to your Attest Cloud with an API key. Add the URL and a key to see the ledger and
          the confirm inbox.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button asChild>
          <Link href="/settings">Open settings</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export function EmptyState({ title, hint, children }: { title: string; hint?: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed py-14 text-center">
      <p className="font-medium">{title}</p>
      {hint && <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">{hint}</p>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
