import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Turbopack only resolves modules inside its root directory, which it
  // auto-detects as this frontend/ folder (it has its own package-lock.json).
  // content/ is a sibling of frontend/, one level up, so a plain relative
  // import of content/story_narrative.json from app code fails with
  // "Module not found" even though the file genuinely exists - confirmed
  // against this Next version's own local docs (turbopack.md's "Root
  // directory" section), not assumed from older webpack-only behavior.
  // Widening the root to the repo root fixes resolution without moving or
  // duplicating content/, which the backend also reads directly by path.
  turbopack: {
    root: path.join(__dirname, ".."),
  },
};

export default nextConfig;
