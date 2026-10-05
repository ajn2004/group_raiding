"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { components } from "@/lib/api/generated/api";

export type Session = components["schemas"]["AuthSessionResponse"];
type State = { status: "loading" } | { status: "anonymous"; notice?: string } | { status: "authenticated"; session: Session } | { status: "error" };
type SessionValue = { state: State; signOut: () => Promise<boolean> };
const Context = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });
  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams(window.location.search);
    const authResult = params.get("auth");
    if (authResult) window.history.replaceState({}, "", window.location.pathname);
    const notice = authResult === "cancelled" ? "Sign-in was cancelled. You can try again." : authResult === "error" ? "Discord sign-in could not be completed. Please try again." : undefined;
    fetch("/api/auth/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error(); return response.json() as Promise<Session>; })
      .then((session) => { if (alive) setState(session.authenticated ? { status: "authenticated", session } : { status: "anonymous", notice }); })
      .catch(() => { if (alive) setState({ status: "error" }); });
    return () => { alive = false; };
  }, []);

  const value = useMemo<SessionValue>(() => ({ state, signOut: async () => {
    if (state.status !== "authenticated") return false;
    try {
      const response = await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": state.session.csrf_token ?? "" } });
      if (response.status === 401) { setState({ status: "anonymous", notice: "Your session expired. Please sign in again." }); return true; }
      if (!response.ok) return false;
      setState({ status: "anonymous" });
      return true;
    } catch { return false; }
  } }), [state]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error("useSession must be used within SessionProvider");
  return value;
}
