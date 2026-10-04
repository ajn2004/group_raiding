"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { HealthStatus } from "@/components/health-status";
import styles from "./page.module.css";
import type { AuthorizationContext } from "@/lib/auth/capabilities";

type Session = { authenticated: boolean; discord_user_id?: string | null; username?: string | null; display_name?: string | null; avatar_url?: string | null; csrf_token?: string | null; authorization?: AuthorizationContext | null };
type AuthState = { status: "loading" } | { status: "anonymous" } | { status: "authenticated"; session: Session } | { status: "error"; message: string };

export default function Home() {
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let active = true;
    const oauthResult = new URLSearchParams(window.location.search).get("auth");
    if (oauthResult) window.history.replaceState({}, "", window.location.pathname);
    fetch("/api/auth/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error(); return response.json() as Promise<Session>; })
      .then((session) => { if (active) {
        if (oauthResult === "cancelled") setAuth({ status: "error", message: "Sign-in was cancelled. You can try again." });
        else if (oauthResult === "error") setAuth({ status: "error", message: "Discord sign-in could not be completed. Please try again." });
        else setAuth(session.authenticated ? { status: "authenticated", session } : { status: "anonymous" });
      } })
      .catch(() => { if (active) setAuth({ status: "error", message: "Sign-in is temporarily unavailable. Please retry." }); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !accountRef.current?.contains(event.target)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        accountButtonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);
  const startSignIn = () => {
    if (busy) return;
    setBusy(true);
    window.location.assign("/api/auth/discord/login");
  };
  const signOut = async () => {
    if (busy || auth.status !== "authenticated") return;
    setBusy(true);
    setActionError(null);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": auth.session.csrf_token ?? "" } });
      if (response.status === 401) { setAuth({ status: "anonymous" }); setActionError("Your session expired. Please sign in again."); return; }
      if (!response.ok) throw new Error();
      setAuth({ status: "anonymous" });
      setMenuOpen(false);
    } catch {
      setActionError("Sign out failed. Please try again.");
    } finally { setBusy(false); }
  };
  const authMessage = actionError || (auth.status === "error" ? auth.message : null);
  const restored = auth.status === "authenticated";
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.wordmark}>Group Raiding</span>
        {auth.status === "authenticated" && <div className={styles.account} ref={accountRef}>
          <button ref={accountButtonRef} className={styles.accountTrigger} type="button" aria-label="Account menu"
            aria-expanded={menuOpen} aria-controls="account-menu" onClick={() => setMenuOpen((open) => !open)}>
            {auth.session.avatar_url ? <Image className={styles.avatar} src={auth.session.avatar_url} alt="" width={30} height={30} unoptimized />
              : <span className={styles.avatarFallback} aria-hidden="true">{(auth.session.display_name || auth.session.username || "?").slice(0, 1).toUpperCase()}</span>}
          </button>
          {menuOpen && <div className={styles.menu} id="account-menu" role="menu">
            <button className={styles.signOut} type="button" role="menuitem" onClick={signOut} disabled={busy}>
              {busy ? "Signing out…" : "Sign out"}
            </button>
            {actionError && <p className={styles.menuError} role="alert">{actionError}</p>}
          </div>}
        </div>}
      </header>
      <main className={styles.main}>
        {auth.status === "loading" ? <p role="status" className={styles.loading}>Checking your session…</p> : !restored && <section className={styles.auth} aria-labelledby="auth-title">
          {
            <>
              <h1 id="auth-title">Sign in to Group Raiding.</h1>
              <p className={styles.supporting}>Use your Discord account to continue.</p>
              <button className={styles.signIn} type="button" onClick={startSignIn} disabled={busy || auth.status === "error" && auth.message.includes("unavailable")}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19.7 5.1a18.4 18.4 0 0 0-4.6-1.4l-.6 1.2a17 17 0 0 0-5 0L8.9 3.7a18 18 0 0 0-4.6 1.4C1.4 9.4.6 13.6 1 17.8a18.5 18.5 0 0 0 5.7 2.9l1.2-2a12 12 0 0 1-1.9-.9l.5-.4a13 13 0 0 0 11 0l.5.4a12 12 0 0 1-1.9.9l1.2 2a18.5 18.5 0 0 0 5.7-2.9c.5-4.9-.8-9.1-3.3-12.7ZM8.7 14.8c-1.1 0-2-1-2-2.2s.9-2.2 2-2.2 2 1 2 2.2-.9 2.2-2 2.2Zm6.6 0c-1.1 0-2-1-2-2.2s.9-2.2 2-2.2 2 1 2 2.2-.9 2.2-2 2.2Z" /></svg>
                {busy ? "Connecting…" : "Sign in with Discord"}
              </button>
            </>
          }
          {authMessage && <div className={styles.authError} role="alert">{authMessage} <button type="button" onClick={() => window.location.reload()}>Retry</button></div>}
        </section>}
      </main>
      <footer className={styles.statusStrip}>
        <HealthStatus />
        <span className={styles.appStatus}>Web app running</span>
      </footer>
    </div>
  );
}
