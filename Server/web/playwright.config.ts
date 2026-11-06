import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const cachedBrowser = path.join(process.env.LOCALAPPDATA || "", "ms-playwright/chromium-1243/chrome-win64/chrome.exe");
export default defineConfig({
  testDir: "./tests", timeout: 30000, workers: 1, reporter: "list",
  use: { baseURL: process.env.VIETOCR_TEST_ORIGIN || "http://127.0.0.1:3000", headless: true,
    launchOptions: fs.existsSync(cachedBrowser) ? { executablePath: cachedBrowser } : {} },
});
