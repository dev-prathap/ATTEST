import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** One colour scale for verification levels, decisions and confirm statuses, used everywhere. */
const TONE: Record<string, string> = {
  verified: "border-verified/40 bg-verified/10 text-verified",
  "verified-custom": "border-verified/40 bg-verified/10 text-verified",
  unverified: "border-unverified/50 bg-unverified/10 text-unverified",
  refuse: "border-unverified/50 bg-unverified/10 text-unverified",
  rejected: "border-unverified/50 bg-unverified/10 text-unverified",
  failed: "border-unverified/50 bg-unverified/10 text-unverified",
  ask: "border-pending/45 bg-pending/10 text-pending",
  pending: "border-pending/45 bg-pending/10 text-pending",
  expired: "border-pending/45 bg-pending/10 text-pending",
  edited: "border-verified/40 bg-verified/10 text-verified",
  approved: "border-verified/40 bg-verified/10 text-verified",
};

export function LevelBadge({ value, className }: { value?: string | null; className?: string }) {
  if (!value) return null;
  return (
    <Badge variant="outline" className={cn("font-medium", TONE[value] ?? "text-muted-foreground", className)}>
      {value}
    </Badge>
  );
}

export const isBad = (level?: string | null) => level === "unverified";
