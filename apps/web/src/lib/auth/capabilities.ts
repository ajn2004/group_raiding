import type { components } from "@/lib/api/generated/api";

export type Capability = NonNullable<components["schemas"]["AuthorizationResponse"]["capabilities"]>[number];
export type AuthorizationContext = components["schemas"]["AuthorizationResponse"];

export function can(authorization: AuthorizationContext | null | undefined, capability: Capability): boolean {
  return authorization?.status === "member" && authorization.capabilities?.includes(capability) === true;
}
