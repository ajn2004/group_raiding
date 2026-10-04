"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./health-status.module.css";
import { api } from "@/lib/api/client";

type HealthState =
  | { status: "loading" }
  | { status: "connected"; apiVersion: string }
  | { status: "error" };

export function HealthStatus() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  const checkHealth = useCallback(async () => {
    setHealth({ status: "loading" });
    try {
      const { data, error } = await api.GET("/api/healthz");
      if (error || !data || data.status !== "ok") setHealth({ status: "error" });
      else setHealth({ status: "connected", apiVersion: data.api_version });
    } catch {
      setHealth({ status: "error" });
    }
  }, []);

  useEffect(() => { void checkHealth(); }, [checkHealth]);

  if (health.status === "loading") {
    return <div className={styles.health} role="status" aria-live="polite" aria-atomic="true"><span className={`${styles.dot} ${styles.loading}`} aria-hidden="true" />Connecting to API…</div>;
  }

  if (health.status === "error") {
    return <div className={styles.health} role="status" aria-live="polite" aria-atomic="true"><span className={`${styles.dot} ${styles.error}`} aria-hidden="true" />API unavailable <button className={styles.retry} type="button" onClick={() => void checkHealth()}>Retry</button></div>;
  }

  return <div className={styles.health} role="status" aria-live="polite" aria-atomic="true"><span className={`${styles.dot} ${styles.connected}`} aria-hidden="true" />API connected · {health.apiVersion}</div>;
}
