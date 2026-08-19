import AxeBuilder from '@axe-core/playwright';
import { expect, Page, test } from '@playwright/test';

const session = {
  authenticated: true,
  csrf_token: 'browser-test-csrf',
  user: { id: 'admin-1', username: 'administrator', name: 'Administrator', role: 'admin' },
};

async function mockCouncilApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const responses: Record<string, unknown> = {
      '/api/auth/session': session,
      '/api/kill-switch': { is_active: false, reason: '', version: 1 },
      '/api/integrations/health': { workflows: {}, publishing: {}, model_gateway: { configured: false, status: 'missing' } },
      '/api/knowledge/documents': { documents: [{
        id: 'doc-1', doc_hash: 'a'.repeat(64), filename: 'evidence.md', status: 'ready',
        chunk_count: 3, index_version: 2, embedding_model: 'BAAI/bge-small-en-v1.5', version: 2,
      }] },
      '/api/knowledge/collections': { collections: [{
        id: 'collection-1', name: 'Product truth', description: 'Reviewed product evidence',
        document_count: 1, document_ids: ['doc-1'], bindings: [], version: 1,
      }] },
      '/api/brain/graph': {
        nodes: [
          { id: 'entity-1', label: 'Astrofood', type: 'organization', status: 'verified', confidence: 0.98, version: 1, active: true },
          { id: 'fact-1', label: 'market: Europe', type: 'fact', status: 'verified', confidence: 0.93, version: 1, active: true },
        ],
        edges: [{ id: 'fact-subject:fact-1', source: 'entity-1', target: 'fact-1', label: 'asserts', status: 'verified', version: 1, active: true }],
        facts: [{ id: 'fact-1', subject_id: 'entity-1', predicate: 'market', value: 'Europe', status: 'verified', confidence: 0.93, citation: 'The target market is Europe.', version: 1 }],
      },
      '/api/brain/conflicts': { conflicts: [] },
      '/api/brain/gaps': { gaps: [] },
      '/api/skills': { skills: [] },
      '/api/learning-suggestions': { suggestions: [] },
    };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(responses[path] ?? {}),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockCouncilApi(page);
  await page.goto('/knowledge');
  await expect(page.getByRole('heading', { name: 'Knowledge & learning' })).toBeVisible();
});

test('has no serious WCAG A/AA violations and exposes selected navigation state', async ({ page }) => {
  await expect(page.getByRole('link', { name: 'Knowledge' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('button', { name: 'Library & collections' })).toHaveAttribute('aria-current', 'page');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([]);
});

test('supports keyboard graph navigation and a non-animated list view', async ({ page }) => {
  const graphTab = page.getByRole('button', { name: 'Entity graph' });
  await graphTab.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Entities, facts & provenance' })).toBeVisible();
  await expect(page.getByRole('img', { name: /2 persisted entities and facts/ })).toBeVisible();
  await page.getByRole('button', { name: 'List view' }).click();
  const astrofood = page.getByText('Astrofood', { exact: true });
  await expect(astrofood).toBeVisible();
  const row = astrofood.locator('xpath=ancestor::article');
  await row.focus();
  await expect(row).toBeFocused();
});

test('stays within a narrow viewport and honors reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Knowledge & learning' })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    motionDuration: getComputedStyle(document.querySelector('.jarvis-orb')!).animationDuration,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
  expect(Number.parseFloat(dimensions.motionDuration)).toBeLessThanOrEqual(0.001);
});
