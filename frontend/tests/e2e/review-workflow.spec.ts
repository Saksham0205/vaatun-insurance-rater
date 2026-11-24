import { test, expect, type Page } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

// Live check of every component added for AI-free rating: extraction note, rating-input
// review (missing badges, rate-card dropdowns, validation errors, recalculate, reset,
// show-all toggle), commission total, persistence on reload, and Re-run extraction.

function envFile(file: string) {
  const out: Record<string, string> = {};
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)=(.*)$/);
    if (m) out[m[1]] = m[2].trim();
  }
  return out;
}

async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /Sign in/ }).click();
  await expect(page.getByRole('heading', { name: 'Policies' })).toBeVisible({ timeout: 30_000 });
}

const review = (page: Page) => page.locator('#review');
const field = (page: Page, label: string) => review(page).locator('label').filter({ hasText: label }).first();
const total = (page: Page) => page.getByTestId('commission-total');

test('review rating inputs, recalculate, reset and re-run on a real HDFC policy', async ({ page }) => {
  test.setTimeout(300_000);
  const repoRoot = path.resolve(process.cwd(), '..');
  const be = envFile(path.join(repoRoot, 'backend', '.env'));
  const fe = envFile(path.join(process.cwd(), '.env.local'));
  const url = fe.NEXT_PUBLIC_SUPABASE_URL || be.SUPABASE_URL;
  const admin = createClient(url, be.SUPABASE_SERVICE_ROLE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const bucket = be.SUPABASE_BUCKET || 'policy-pdfs';
  let userId = '';
  try {
    const email = `vaatun-pw-review-${randomUUID().slice(0, 8)}@example.com`;
    const password = `${randomUUID()}Aa9!`;
    const { data, error } = await admin.auth.admin.createUser({ email, password, email_confirm: true });
    expect(error).toBeNull();
    userId = data.user!.id;

    await signIn(page, email, password);
    // Sidebar: removed items are gone; it collapses to an icon rail and remembers that.
    const sidebar = page.getByTestId('sidebar');
    for (const removed of ['History', 'Evidence-first workflow', 'Help & support']) {
      await expect(sidebar.getByText(removed)).toHaveCount(0);
    }
    await expect(sidebar.getByText('Overview')).toBeVisible();
    // Retry the click until React has hydrated the header (dev mode compiles on demand).
    await expect(async () => {
      if (await sidebar.getAttribute('data-collapsed') !== 'true') {
        await page.getByRole('button', { name: 'Collapse sidebar' }).click({ timeout: 2_000 });
      }
      await expect(sidebar).toHaveAttribute('data-collapsed', 'true', { timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await expect(sidebar.getByText('Overview')).toHaveCount(0);
    await expect(sidebar.getByRole('link', { name: 'Overview' })).toHaveAttribute('title', 'Overview');
    await expect.poll(async () => (await sidebar.boundingBox())!.width).toBeLessThan(80);  // after the 200ms transition
    await page.screenshot({ path: 'test-results/sidebar-collapsed.png', mask: [page.getByTestId('account-email')] });
    await page.reload();
    await expect(sidebar).toHaveAttribute('data-collapsed', 'true', { timeout: 30_000 });
    await expect(sidebar.getByRole('button', { name: 'Sign out' })).toBeVisible();
    await page.getByRole('button', { name: 'Expand sidebar' }).click();
    await expect(sidebar.getByText('Overview')).toBeVisible();
    await expect.poll(async () => (await sidebar.boundingBox())!.width).toBeGreaterThan(200);
    await page.screenshot({ path: 'test-results/sidebar-expanded.png', mask: [page.getByTestId('account-email')] });

    const fixture = path.join(repoRoot, 'sample-policies', 'pvt-car-comprehensive-hdfc-ergo.pdf');
    // Re-attach until React has hydrated and registered the file (enables the button).
    // Clearing first matters: re-selecting the same file fires no change event.
    const uploadButton = page.getByRole('button', { name: 'Upload PDF' });
    await expect(async () => {
      await page.locator('input[type=file]').setInputFiles([]);
      await page.locator('input[type=file]').setInputFiles(fixture);
      await expect(uploadButton).toBeEnabled({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await uploadButton.click();
    await expect(page.getByRole('status').filter({ hasText: 'Uploaded' })).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: /Analyze/ }).click();
    await expect(page).toHaveURL(/\/documents\/[0-9a-f-]+$/, { timeout: 120_000 });

    // Extraction (no AI) and extracted values with evidence.
    await expect(page.getByText(/Read without AI: local OCR on \d+ scanned page/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Mahindra BOLERO NEO-N10 (R)')).toBeVisible();
    await expect(page.getByText('₹8,053').first()).toBeVisible();

    // Review panel: fuel is not printed, so it is flagged Missing and nothing is estimated.
    await expect(page.getByRole('heading', { name: 'Review rating inputs' })).toBeVisible();
    await expect(field(page, 'Fuel')).toContainText('Missing');
    await expect(field(page, 'OD premium')).toContainText('PDF: 8053');
    await expect(total(page)).toHaveText('—');
    await expect(page.getByTestId('recalculate')).toBeDisabled();
    await expect(page.getByText('Assessment incomplete')).toBeVisible();

    // Show-all toggle reveals inputs other rate cards use.
    await expect(field(page, 'Tata AIG territory')).toHaveCount(0);
    await review(page).getByRole('button', { name: 'Show all inputs' }).click();
    await expect(field(page, 'Tata AIG territory')).toBeVisible();
    await review(page).getByRole('button', { name: 'Show rate-card inputs only' }).click();

    // Server-side validation error is shown in the panel.
    await review(page).getByRole('button', { name: 'Show all inputs' }).click();
    await field(page, 'Engine capacity').locator('input').fill('abc');
    await page.getByTestId('recalculate').click();
    await expect(review(page).getByRole('alert')).toContainText('whole number');
    await field(page, 'Engine capacity').locator('input').fill('');

    // Supply fuel -> commission computed from the HDFC grid: 8053 x 15% = 1207.95.
    await field(page, 'Fuel').locator('select').selectOption('Diesel');
    await expect(page.getByTestId('recalculate')).toBeEnabled();
    await page.getByTestId('recalculate').click();
    await expect(total(page)).toHaveText('₹1,207.95', { timeout: 30_000 });
    await expect(field(page, 'Fuel')).toContainText('Reviewer');
    await expect(review(page).getByText('1 input(s) supplied by reviewer')).toBeVisible();
    await expect(page.getByText('15%', { exact: true })).toBeVisible();
    await expect(page.getByText('OD premium 8053 × 15% = 1207.95')).toBeVisible();
    await expect(page.getByText('Assessment incomplete')).toHaveCount(0);

    // Persisted: survives a reload.
    await page.reload();
    await expect(total(page)).toHaveText('₹1,207.95', { timeout: 30_000 });
    await expect(field(page, 'Fuel')).toContainText('Reviewer');
    await page.screenshot({ path: 'test-results/review-recalculated.png', fullPage: true,
      mask: [page.getByTestId('account-email')], maskColor: '#eef0f6' });

    // Reset returns to PDF-only values.
    await review(page).getByRole('button', { name: 'Reset to PDF values' }).click();
    await expect(total(page)).toHaveText('—', { timeout: 30_000 });
    await expect(field(page, 'Fuel')).toContainText('Missing');

    // Re-run extraction reads the PDF again and keeps the page usable.
    await page.getByRole('button', { name: 'Re-run extraction' }).click();
    await expect(page.getByRole('heading', { name: 'Review rating inputs' })).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText('Mahindra BOLERO NEO-N10 (R)')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Re-run extraction' })).toBeEnabled({ timeout: 120_000 });
  } finally {
    if (userId) {
      try {
        const docs = await admin.from('documents').select('storage_path').eq('user_id', userId);
        const paths = (docs.data || []).map(x => x.storage_path);
        if (paths.length) await admin.storage.from(bucket).remove(paths);
        await admin.auth.admin.deleteUser(userId);
      } catch { /* best-effort cleanup */ }
    }
  }
});
