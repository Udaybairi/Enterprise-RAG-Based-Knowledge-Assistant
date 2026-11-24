import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

/**
 * End-to-end tests against the real stack: FastAPI backend (offline deterministic provider, fresh
 * temporary database each run) + the production Next.js build. Run `npm run build` first.
 */
const dataDir = path.join(os.tmpdir(), `rag-e2e-${Date.now()}`);
const python = process.env.PYTHON || "python";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // tests share one backend database (the first registered user becomes admin)
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "off",
    ...(process.env.PW_REDUCED_MOTION ? { reducedMotion: "reduce" as const } : {}),
    ...(process.env.PW_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH } } : {}),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port 8000`,
      cwd: path.join(__dirname, "..", "backend"),
      url: "http://localhost:8000/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        LLM_PROVIDER: "fake",
        ENVIRONMENT: "development",
        DATA_DIR: dataDir,
        DATABASE_URL: "",
        EMBEDDING_DIMENSION: "384",
        SIMILARITY_THRESHOLD: "0.15", // the offline hash embeddings produce low cosine values
        RATE_LIMIT_ENABLED: "false",
        CORS_ORIGINS: "http://localhost:3000",
      },
    },
    {
      command: "npm run start",
      url: "http://localhost:3000/login",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
