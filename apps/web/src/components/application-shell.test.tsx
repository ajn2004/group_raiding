import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApplicationShell } from "./application-shell";
import { SessionProvider } from "@/lib/auth/session";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ href, children, onClick, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => <a href={href} {...props} onClick={(event) => { event.preventDefault(); onClick?.(event); }}>{children}</a> }));
vi.mock("next/image", () => ({ default: ({ src }: { src: string }) => <span data-testid="avatar-image" data-src={src} /> }));
vi.mock("@/components/health-status", () => ({ HealthStatus: () => <span>API connected · v1</span> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); pathname = "/"; window.history.replaceState({}, "", "/"); });
const response = (data: object) => new Response(JSON.stringify(data), { status: 200 });
const session = (authorization: object = { status: "member", is_member: true, capabilities: ["app.view", "players.manage", "coaching.configure", "usage.view"] }) => ({ authenticated: true, display_name: "Raid Leader", avatar_url: "https://cdn.example/avatar.png", csrf_token: "csrf", authorization });
function renderShell() { return render(<SessionProvider><ApplicationShell><p>Placeholder route content</p></ApplicationShell></SessionProvider>); }

describe("application shell", () => {
  it("holds a session loading state and presents public product information with Discord sign-in", async () => {
    let finish!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    renderShell();
    expect(screen.getByRole("status")).toHaveTextContent("Loading your Group Raiding workspace");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    finish(response({ authenticated: false }));
    expect(await screen.findByRole("heading", { name: "Turn raid logs into better pulls." })).toBeVisible();
    expect(screen.getByText(/actionable raid and player coaching/)).toBeVisible();
    expect(screen.getByText(/Deterministic analysis identifies what happened/)).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Sign in with Discord" })[0]).toHaveAttribute("href", "/api/auth/discord/login");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("shows identity, avatar, account action and all permitted management links", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session())));
    renderShell();
    expect(await screen.findByRole("navigation", { name: "Main navigation" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Player Linkage" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Coaching Configuration" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Usage" })).toBeVisible();
    expect(screen.getAllByText("Raid Leader").length).toBeGreaterThan(0);
    expect(screen.getByTestId("avatar-image")).toHaveAttribute("data-src", "https://cdn.example/avatar.png");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  it("maps each destination to its distinct capability and guards direct route content", async () => {
    pathname = "/";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session({ status: "member", is_member: true, capabilities: ["app.view", "usage.view"] }))));
    renderShell();
    expect(await screen.findByRole("navigation", { name: "Main navigation" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Player Linkage" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Usage" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Coaching Configuration" })).not.toBeInTheDocument();
    pathname = "/players";
    cleanup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session({ status: "member", is_member: true, capabilities: ["app.view", "usage.view"] }))));
    renderShell();
    expect(await screen.findByRole("heading", { name: "Access not available" })).toBeVisible();
    expect(screen.queryByText("Placeholder route content")).not.toBeInTheDocument();
  });

  it.each([
    ["/players/details", "players.manage"],
    ["/coaching/profiles/123", "coaching.configure"],
  ])("guards privileged route family %s and does not render its child", async (route, capability) => {
    pathname = route;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session({ status: "member", is_member: true, capabilities: ["app.view", capability === "players.manage" ? "coaching.configure" : "players.manage"] }))));
    renderShell();
    expect(await screen.findByRole("heading", { name: "Access not available" })).toBeVisible();
    expect(screen.queryByText("Placeholder route content")).not.toBeInTheDocument();
  });

  it("does not apply the players rule to similarly prefixed routes", async () => {
    pathname = "/players-old";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session({ status: "member", is_member: true, capabilities: ["app.view"] }))));
    renderShell();
    expect(await screen.findByRole("navigation", { name: "Main navigation" })).toBeVisible();
    expect(screen.getByText("Placeholder route content")).toBeVisible();
  });

  it("requires app.view for shell access, including for non-members and management-only members", async () => {
    for (const authorization of [
      { status: "member", is_member: true, capabilities: [] },
      { status: "not_member", is_member: false, capabilities: [] },
      { status: "member", is_member: true, capabilities: ["players.manage"] },
    ]) {
      cleanup();
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(session(authorization))));
      renderShell();
      expect(await screen.findByRole("heading", { name: "Access not available" })).toBeVisible();
      expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Player Linkage" })).not.toBeInTheDocument();
    }
  });

  it("uses a fallback identity avatar and supports opening, Escape-closing, focus return and navigation close", async () => {
    pathname = "/";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...session(), avatar_url: null })));
    renderShell();
    const toggle = await screen.findByRole("button", { name: "Open navigation menu" });
    expect(screen.getByText("R", { selector: "span" })).toBeVisible();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const firstLink = screen.getByRole("link", { name: "Overview" });
    expect(firstLink).toHaveFocus();
    expect(screen.getByRole("main", { name: "" })).toHaveAttribute("inert");
    toggle.focus();
    expect(toggle).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(firstLink).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("link", { name: "Player Linkage" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
  });

  it("calls the existing logout endpoint and transitions to the anonymous landing", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(session())).mockResolvedValueOnce(response({ signed_out: true }));
    vi.stubGlobal("fetch", fetchMock);
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Turn raid logs into better pulls." })).toBeVisible();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }));
  });

  it("keeps Discord sign-in callback feedback visible", async () => {
    window.history.replaceState({}, "", "/?auth=cancelled");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ authenticated: false })));
    renderShell();
    expect(await screen.findByText("Sign-in was cancelled. You can try again.")).toBeVisible();
  });

  it("keeps the authenticated shell and explains a failed sign-out", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(session())).mockResolvedValueOnce(new Response("{}", { status: 503 })));
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign out failed");
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  });
});
