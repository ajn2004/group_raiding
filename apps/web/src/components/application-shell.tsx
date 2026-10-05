"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { can, type Capability } from "@/lib/auth/capabilities";
import { useSession } from "@/lib/auth/session";
import { HealthStatus } from "@/components/health-status";
import styles from "./application-shell.module.css";

const destinations: { label: string; href: string; capability?: Capability }[] = [
  { label: "Overview", href: "/" },
  { label: "Player Linkage", href: "/players", capability: "players.manage" },
  { label: "Coaching Configuration", href: "/coaching", capability: "coaching.configure" },
  { label: "Usage", href: "/usage", capability: "usage.view" },
];

export function ApplicationShell({ children }: { children: React.ReactNode }) {
  const { state, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const toggleRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const pathname = usePathname();
  const router = useRouter();
  const session = state.status === "authenticated" ? state.session : undefined;
  const authorization = session?.authorization;

  useEffect(() => {
    if (!open) return;
    sidebarRef.current?.querySelector<HTMLElement>("a[href]")?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); toggleRef.current?.focus(); }
      if (event.key === "Tab") {
        const focusable = sidebarRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!sidebarRef.current?.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
        else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  if (state.status === "loading") return <main className={styles.loading} role="status">Loading your Group Raiding workspace…</main>;
  if (state.status === "error") return <main className={styles.loading} role="alert">Your session could not be checked. <button onClick={() => window.location.reload()}>Retry</button></main>;
  if (state.status === "anonymous") return <div className={styles.publicPage}>
    <header className={styles.publicHeader}><Link href="/" className={styles.brand}>Group Raiding</Link><a className={styles.smallCta} href="/api/auth/discord/login">Sign in with Discord</a></header>
    <main className={styles.landing}>
      <p className={styles.eyebrow}>Raid insight, grounded in evidence</p>
      <h1>Turn raid logs into better pulls.</h1>
      <p className={styles.intro}>Group Raiding turns raid-log data into actionable raid and player coaching. Connect with Discord to access the application.</p>
      <a href="/api/auth/discord/login" className={styles.cta}>Sign in with Discord</a>
      {state.notice && <p className={styles.notice} role="status">{state.notice}</p>}
      <div className={styles.explainers}>
        <section><h2>Measured first</h2><p>Deterministic analysis identifies what happened in the logs. Generated coaching interpretation stays distinct from those measured facts.</p></section>
        <section><h2>Configure once</h2><p>Coaching configuration managed in the web application drives the Discord Pull Coach.</p></section>
        <section><h2>Discord identity</h2><p>Discord is used for identity and application access.</p></section>
      </div>
    </main><footer className={styles.statusStrip}><HealthStatus /><span>Web app running</span></footer>
  </div>;
  if (!session) return null;

  if (!can(authorization, "app.view")) return <main className={styles.forbidden}>
    <h1>Access not available</h1><p>Your current Discord account does not have access to this application.</p>
  </main>;

  const allowed = destinations.find((item) => item.capability && (pathname === item.href || pathname.startsWith(`${item.href}/`)))?.capability;
  if (allowed && !can(authorization, allowed)) return <main className={styles.forbidden}>
    <h1>Access not available</h1><p>Your current Discord access does not include this destination.</p><Link href="/">Return to overview</Link>
  </main>;

  const name = session.display_name || session.username || "Discord user";
  const handleSignOut = async () => {
    setBusy(true); setError("");
    if (await signOut()) router.replace("/");
    else setError("Sign out failed. Please try again.");
    setBusy(false);
  };
  const navigation = <nav aria-label="Main navigation"><ul>{destinations.filter((item) => !item.capability || can(authorization, item.capability)).map((item) =>
    <li key={item.href}><Link href={item.href} aria-current={pathname === item.href ? "page" : undefined} onClick={() => setOpen(false)}>{item.label}</Link></li>)}</ul></nav>;

  return <div className={styles.app}>
    <header className={styles.topbar}><button ref={toggleRef} className={styles.menuButton} type="button" aria-label={open ? "Close navigation menu" : "Open navigation menu"} aria-expanded={open} aria-controls="app-sidebar" onClick={() => setOpen((value) => !value)}>☰</button><Link href="/" className={styles.brand}>Group Raiding</Link><span className={styles.mobileName}>{name}</span></header>
    {open && <button className={styles.scrim} aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside ref={sidebarRef} id="app-sidebar" className={`${styles.sidebar} ${open ? styles.sidebarOpen : ""}`}>
      {navigation}
      <section className={styles.account} aria-label="Account">
        {session.avatar_url ? <Image src={session.avatar_url} width={36} height={36} alt="" unoptimized className={styles.avatar} /> : <span className={styles.avatarFallback} aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>}
        <span className={styles.accountName}>{name}</span>
        <button type="button" className={styles.signOut} onClick={handleSignOut} disabled={busy}>{busy ? "Signing out…" : "Sign out"}</button>
        {error && <p role="alert">{error}</p>}
      </section>
    </aside>
    <main className={styles.content} inert={open}>{children}</main>
    <footer className={styles.statusStrip}><HealthStatus /><span>Web app running</span></footer>
  </div>;
}
