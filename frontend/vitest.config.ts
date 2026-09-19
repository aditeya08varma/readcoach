import path from "path";
import { defineConfig } from "vitest/config";

// Lightweight unit-test runner for frontend/lib - the only test runner this
// project has (zero automated tests existed before this pass, despite
// extensive "found via real manual testing" regression comments throughout
// the code that nothing actually guarded against). Vitest over Jest: this
// project is already a Vite-less but ESM/TS-native Next 16 + React 19 app
// with no Babel/Jest config of its own, and Vitest's Vite-based transform
// handles that (plus the `@/*` path alias below, matching tsconfig.json)
// with effectively zero extra config, whereas Jest would need its own
// ts-jest/babel + moduleNameMapper setup duplicating what Next already does.
//
// jsdom environment (not "node"): lib/confettiPop.ts is a browser-only
// module (canvas, document, window, requestAnimationFrame) and needs a real
// DOM to exercise for real, and Node's own global fetch/AbortController
// (used by lib/api.ts's tests) are unaffected by running under jsdom.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["**/node_modules/**", "**/.next/**"],
  },
});
