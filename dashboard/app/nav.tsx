"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Inbox, ScrollText, Settings } from "lucide-react";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Ledger", icon: ScrollText },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
      <nav className="mx-auto flex w-full max-w-7xl items-center gap-1 px-4 py-2.5 md:px-6">
        <Link href="/" className="mr-4 font-semibold tracking-tight">
          Attest
        </Link>
        {LINKS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
              path === href && "bg-accent font-medium text-foreground",
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        ))}
        <span className="ml-auto hidden text-xs text-muted-foreground sm:block">
          Decide · Gate · Verify · Attest
        </span>
      </nav>
    </header>
  );
}
