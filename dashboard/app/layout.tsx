import type { Metadata } from "next";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";
import Nav from "./nav";

export const metadata: Metadata = {
  title: "Attest",
  description: "Prove what your AI agent actually did.",
};

/** Follow the OS light/dark setting. Inline so the first paint already has the right theme. */
const theme = `(function(){try{var m=matchMedia("(prefers-color-scheme: dark)"),a=function(e){document.documentElement.classList.toggle("dark",e.matches)};a(m);m.addEventListener("change",a)}catch(e){}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: theme }} />
      </head>
      <body className="min-h-svh bg-background text-foreground antialiased">
        <Nav />
        <main className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6">{children}</main>
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
