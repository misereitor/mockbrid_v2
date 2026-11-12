import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const PASSWORD = 'SenhaForte123!';

const SCREEN_HTML = `
<div class="p-8">
  <div class="bg-white p-6 rounded-xl" style="width: 420px">
    <h1 class="text-2xl font-bold" style="color: #111111">Título Export</h1>
    <p style="color: #444444">Texto exportado do bundle</p>
  </div>
</div>`;

async function register(request: APIRequestContext, prefix: string) {
  const email = `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 6)}@empresa.com`;
  const res = await request.post('/api/auth/register', {
    data: {
      name: 'Usuário Bundle',
      email,
      password: PASSWORD,
      organization_name: `Org Bundle ${prefix}`,
    },
  });
  expect(res.ok()).toBeTruthy();
}

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'mockbird_csrf')?.value;
  return token ? { 'X-CSRF-Token': token } : {};
}

test('editor exporta bundle com camadas para Figma/Penpot', async ({ page, context }) => {
  await register(context.request, 'bundle');
  await page.goto('/');

  const projectRes = await context.request.post('/api/projects', {
    data: { name: 'Projeto Bundle' },
    headers: await csrf(page),
  });
  expect(projectRes.ok()).toBeTruthy();
  const project = await projectRes.json();

  const screensRes = await context.request.get(`/api/projects/${project.id}/screens`);
  expect(screensRes.ok()).toBeTruthy();
  const screens = await screensRes.json();
  expect(screens.length).toBeGreaterThan(0);

  const updateRes = await context.request.put(`/api/screens/${screens[0].id}`, {
    data: { html_content: SCREEN_HTML, css_content: '', js_content: '' },
    headers: await csrf(page),
  });
  expect(updateRes.ok()).toBeTruthy();

  await page.goto(`/editor/${project.id}`);
  const exportButton = page.getByRole('button', { name: /Figma\/Penpot/ });
  await expect(exportButton).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 60_000 }),
    exportButton.click(),
  ]);
  const filePath = await download.path();
  expect(filePath).toBeTruthy();
  const bundle = JSON.parse(readFileSync(filePath as string, 'utf8'));

  expect(bundle.format).toBe('mockbird.design-bundle');
  expect(bundle.version).toBe(1);
  expect(bundle.project.name).toBe('Projeto Bundle');
  expect(bundle.screens.length).toBeGreaterThan(0);

  const screen = bundle.screens[0];
  expect(screen.width).toBeGreaterThan(0);
  expect(screen.height).toBeGreaterThan(0);
  expect(Array.isArray(screen.layers)).toBe(true);

  const texts = screen.layers.filter((layer: any) => layer.type === 'text');
  const textContents = texts.map((layer: any) => layer.text);
  expect(textContents).toContain('Título Export');
  expect(textContents).toContain('Texto exportado do bundle');

  const heading = texts.find((layer: any) => layer.text === 'Título Export');
  expect(heading.fontSize).toBeGreaterThan(20);
  expect(heading.fontWeight).toBeGreaterThanOrEqual(600);
  expect(heading.x).toBeGreaterThan(0);
  expect(heading.y).toBeGreaterThan(0);

  const card = screen.layers.find(
    (layer: any) => layer.type === 'rect' && layer.fill === '#ffffff' && layer.width > 300,
  );
  expect(card).toBeTruthy();
});

test('extrator da extensão captura a página em camadas', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Bem-vindo de volta' })).toBeVisible();

  const scriptPath = path.resolve(process.cwd(), '../integrations/browser-extension/dom-layers.js');
  await page.addScriptTag({ path: scriptPath });

  const captured = await page.evaluate(() => (window as any).__mockbirdCapturePage());
  expect(captured.width).toBeGreaterThan(300);
  expect(captured.height).toBeGreaterThan(300);
  expect(Array.isArray(captured.layers)).toBe(true);
  expect(captured.layers.length).toBeGreaterThan(3);
  expect(captured.layers.some((layer: any) => layer.type === 'text' && layer.text)).toBe(true);
});
