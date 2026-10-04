import { describe, expect, it } from "vitest";
import { can } from "./capabilities";

describe("capability visibility", () => {
  it("allows only capabilities in a current member authorization context", () => {
    expect(can({ is_member: true, status: "member", capabilities: ["app.view", "usage.view"] }, "usage.view")).toBe(true);
    expect(can({ is_member: true, status: "member", capabilities: ["app.view"] }, "usage.view")).toBe(false);
    expect(can({ is_member: false, status: "unavailable", capabilities: ["admin.manage_rbac"] }, "admin.manage_rbac")).toBe(false);
    expect(can(undefined, "app.view")).toBe(false);
  });
});
