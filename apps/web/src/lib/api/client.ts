import createClient from "openapi-fetch";
import type { paths } from "./generated/api";

export const api = createClient<paths>({ baseUrl: "" });
