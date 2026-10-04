import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import Home from "./page";

vi.mock("@/components/health-status", () => ({ HealthStatus: () => <div>API connected</div> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps controls hidden while restoring the session, then shows sign in for anonymous users", async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
  render(<Home />);
  expect(screen.getByRole("status")).toHaveTextContent("Checking your session");
  expect(screen.queryByRole("button", { name: "Sign in with Discord" })).not.toBeInTheDocument();
  finish(new Response(JSON.stringify({ authenticated: false }), { status: 200 }));
  expect(await screen.findByRole("heading", { name: "Sign in to Group Raiding." })).toBeVisible();
  expect(screen.getByRole("button", { name: "Sign in with Discord" })).toBeEnabled();
});

it("shows an avatar menu in the header and signs out successfully", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, discord_user_id: "42", display_name: "Raider", avatar_url: "https://cdn.example/avatar.png", csrf_token: "csrf" }), { status: 200 })).mockResolvedValueOnce(new Response(JSON.stringify({ signed_out: true }), { status: 200 })));
  render(<Home />);
  const trigger = await screen.findByRole("button", { name: "Account menu" });
  expect(trigger.querySelector("img")).toBeInTheDocument();
  expect(screen.queryByText("Raider")).not.toBeInTheDocument();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign in with Discord" })).toBeVisible());
  expect(fetch).toHaveBeenLastCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }));
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("surfaces an unavailable session endpoint separately from anonymous", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<Home />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in is temporarily unavailable");
  expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
});

it("keeps the avatar menu open and shows the error when sign out fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, display_name: "Raider", csrf_token: "csrf" }), { status: 200 })).mockResolvedValueOnce(new Response("{}", { status: 503 })));
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign out failed");
  expect(screen.getByRole("menu")).toBeVisible();
  expect(screen.getByRole("button", { name: "Account menu" })).toBeVisible();
});

it("closes outside and returns focus to the avatar on Escape", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ authenticated: true, username: "raider" }), { status: 200 })));
  render(<Home />);
  const trigger = await screen.findByRole("button", { name: "Account menu" });
  fireEvent.click(trigger);
  expect(screen.getByRole("menu")).toBeVisible();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("prevents duplicate logout requests while a logout is pending", async () => {
  let finish!: (response: Response) => void;
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, csrf_token: "csrf" }), { status: 200 }))
    .mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
  vi.stubGlobal("fetch", fetchMock);
  render(<Home />);
  fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
  const signOut = screen.getByRole("menuitem", { name: "Sign out" });
  fireEvent.click(signOut);
  fireEvent.click(signOut);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(signOut).toBeDisabled();
  finish(new Response("{}", { status: 200 }));
  await screen.findByRole("button", { name: "Sign in with Discord" });
});
