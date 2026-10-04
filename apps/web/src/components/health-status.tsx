"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type HealthState =
  | { status: "loading" }
  | { status: "connected"; apiVersion: string }
  | { status: "error" };

export function HealthStatus() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    let active = true;

    api.GET("/api/healthz").then(({ data, error }) => {
      if (!active) return;
      if (error || !data || data.status !== "ok") {
        setHealth({ status: "error" });
      } else {
        setHealth({ status: "connected", apiVersion: data.api_version });
      }
    }).catch(() => {
      if (active) setHealth({ status: "error" });
    });

    return () => { active = false; };
  }, []);

  if (health.status === "loading") {
    return <p role="status">Checking Python API…</p>;
  }

  if (health.status === "error") {
    return <p role="alert">Python API is unavailable. Check that the API is running and try again.</p>;
  }

  return <p role="status">Python API connected (version {health.apiVersion}).</p>;
}
