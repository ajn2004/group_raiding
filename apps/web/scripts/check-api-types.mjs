import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

const contractPath = resolve("src/lib/api/generated/openapi.json");
const typesPath = resolve("src/lib/api/generated/api.d.ts");
const schema = JSON.parse(await readFile(contractPath, "utf8"));
const expected = COMMENT_HEADER + astToString(await openapiTS(schema));
const actual = await readFile(typesPath, "utf8");

if (actual !== expected) {
  console.error(
    "Generated API types are out of date. Run `pnpm generate:api` from apps/web.",
  );
  process.exitCode = 1;
}
