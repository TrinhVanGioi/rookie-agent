import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";

const outdir = "dist";

// Each entry is bundled into one file; MV3 pages and workers load them by name.
const entryPoints = {
  index: "src/index.ts",
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

if (existsSync("public")) {
  await cp("public", outdir, { recursive: true });
}
