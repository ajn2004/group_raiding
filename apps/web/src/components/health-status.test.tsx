import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { HealthStatus } from "./health-status";

vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn() },
}));

import { api } from "@/lib/api/client";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("HealthStatus", () => {
  it("shows loading, then the connected API version", async () => {
    let resolveHealth!: (value: { data: { status: string; api_version: string } }) => void;
    vi.mocked(api.GET).mockReturnValue(new Promise((resolve) => { resolveHealth = resolve; }) as never);

    render(<HealthStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking Python API");
    resolveHealth({ data: { status: "ok", api_version: "v1" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("connected (version v1)"));
  });

  it("shows an error when the API request fails", async () => {
    vi.mocked(api.GET).mockResolvedValue({ data: undefined, error: { detail: "offline" } } as never);
    render(<HealthStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Python API is unavailable");
  });
});
