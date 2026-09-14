import type { Metadata } from "next";
import "./globals.css";
import Nav from "./nav";

export const metadata: Metadata = { title: "Attest", description: "Prove what your AI agent actually did." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
