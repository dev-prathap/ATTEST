"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Nav() {
  const p = usePathname();
  const item = (href: string, label: string) => (
    <Link href={href} className={p === href ? "active" : ""}>{label}</Link>
  );
  return (
    <nav className="nav">
      <b>Attest</b>
      {item("/", "Ledger")}
      {item("/inbox", "Inbox")}
      {item("/settings", "Settings")}
      <span className="muted" style={{ marginLeft: "auto" }}>Decide · Gate · Verify · Attest</span>
    </nav>
  );
}
