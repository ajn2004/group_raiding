import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [...compat.extends("next/core-web-vitals", "next/typescript")];

const config = [
  { ignores: [".next/**", "next-env.d.ts", "src/lib/api/generated/api.d.ts"] },
  ...eslintConfig,
];

export default config;
