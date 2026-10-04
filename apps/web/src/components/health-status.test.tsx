import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    expect(screen.getByRole("status")).toHaveTextContent("Connecting to API…");
    resolveHealth({ data: { status: "ok", api_version: "v1" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("API connected · v1"));
  });

  it("shows failure and retries the health request", async () => {
    const user = userEvent.setup();
    vi.mocked(api.GET)
      .mockResolvedValueOnce({ data: undefined, error: { detail: "offline" } } as never)
      .mockResolvedValueOnce({ data: { status: "ok", api_version: "v2" } } as never);
    render(<HealthStatus />);
    expect(await screen.findByRole("status")).toHaveTextContent("API unavailable");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("API connected · v2"));
    expect(api.GET).toHaveBeenCalledTimes(2);
  });
});
