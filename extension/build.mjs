import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";

const outdir = "dist";

// Each entry is bundled into one file; MV3 pages and workers load them by name.
const entryPoints = {
  background: "src/background.ts",
  sidepanel: "src/sidepanel.ts",
};

await rm(outdir, { recursive: true, force: true });
await mkdir(outdir, { recursive: true });

await build({
  entryPoints,
  outdir,
  bundle: true,
  format: "esm",
  target: "chrome120",
  sourcemap: true,
  logLevel: "info",
});

// A content script is injected as a classic script, so it must not be a module.
await build({
  entryPoints: { content: "src/content.ts" },
  outdir,
  bundle: true,
  format: "iife",
  target: "chrome120",
  sourcemap: false,
  logLevel: "info",
});

if (existsSync("public")) {
  await cp("public", outdir, { recursive: true });
}
