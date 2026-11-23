import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: { baseURL: 'http://localhost:3000', trace: 'retain-on-failure', screenshot: 'only-on-failure', ...devices['Desktop Chrome'] },
  webServer: [
    { command: 'npm run dev -- --hostname 127.0.0.1', url: 'http://127.0.0.1:3000', cwd: process.cwd(), reuseExistingServer: !process.env.CI, timeout: 120_000 },
    { command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8000', url: 'http://127.0.0.1:8000/api/v1/health', cwd: '../backend', reuseExistingServer: !process.env.CI, timeout: 120_000 },
  ],
});
