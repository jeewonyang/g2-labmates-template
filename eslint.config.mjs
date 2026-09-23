import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // Keep in sync with tsconfig.json "exclude" and .gitignore. These are not
    // part of the Second Brain app: AppDev/ holds five unrelated sibling apps
    // and archive/ is ~336k backed-up files. Without these, `npm run lint`
    // reports ~900 errors from code this project does not own.
    ignores: [
      "node_modules/**",
      ".next/**",
      ".next-dev/**",
      ".next-stale*/**",
      "out/**",
      "next-env.d.ts",
      "AppDev/**",
      "archive/**",
      "VAULT/**",
    ],
  },
];

export default eslintConfig;
