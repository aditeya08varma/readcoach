import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next, widened from ".next/**" to
    // "**/.next/**": this repo's next.config.ts intentionally widens
    // Turbopack's root to the monorepo root (see its own comment, for
    // resolving content/ imports), which as a side effect makes the running
    // dev server also write dev-only chunk output into a nested
    // frontend/frontend/.next/ - a real, reproducible, regenerating build
    // artifact (not source), found by audit because the un-widened pattern
    // let `eslint .` lint minified Turbopack chunks and fail on generated
    // code no one owns. Matching ".next" at any depth keeps this ignore's
    // original intent (never lint Next's own build output) actually true
    // for how this project's dev server behaves in practice.
    "**/.next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
