import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
// Both Python apps share the venv created in server/ (see CLAUDE.md).
const python = path.join(repoRoot, "server", ".venv", "Scripts", "python.exe");

export const MOCK_SITE_URL = "http://localhost:8001";
export const SERVER_URL = "http://localhost:8000";
// Task 10.8: the admin page with logins on (the dev people of config/roles.json), on its own database.
export const ADMIN_URL = "http://localhost:8002";

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { trace: "retain-on-failure" },
  webServer: [
    {
      command: `"${python}" -m uvicorn app:app --port 8001`,
      cwd: path.join(repoRoot, "mock-site"),
      url: `${MOCK_SITE_URL}/health`,
      reuseExistingServer: true,
    },
    {
      command: `"${python}" -m uvicorn app.main:app --port 8000`,
      cwd: path.join(repoRoot, "server"),
      env: { ROOKIE_DB: path.join(os.tmpdir(), "rookie-e2e.db") },
      url: `${SERVER_URL}/health`,
      reuseExistingServer: true,
    },
    {
      command: `"${python}" -m uvicorn app.main:app --port 8002`,
      cwd: path.join(repoRoot, "server"),
      env: { ROOKIE_DB: path.join(os.tmpdir(), `rookie-admin-e2e-${process.pid}.db`), ROOKIE_AUTH: "dev" },
      url: `${ADMIN_URL}/health`,
      reuseExistingServer: false,
    },
  ],
});
