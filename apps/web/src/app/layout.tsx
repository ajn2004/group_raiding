import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Group Raiding",
  description: "Group Raiding raid analysis tools",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
