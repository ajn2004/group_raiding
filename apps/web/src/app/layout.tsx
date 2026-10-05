import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "@/lib/auth/session";
import { ApplicationShell } from "@/components/application-shell";

export const metadata: Metadata = {
  title: "Group Raiding",
  description: "Group Raiding raid analysis tools",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><SessionProvider><ApplicationShell>{children}</ApplicationShell></SessionProvider></body></html>;
}
