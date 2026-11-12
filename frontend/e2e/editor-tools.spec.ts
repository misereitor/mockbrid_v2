import { test, expect, type APIRequestContext, type FrameLocator, type Page } from '@playwright/test';

const PASSWORD = 'SenhaForte123!';

const SCREEN_HTML = `
  <div class="p-8 flex flex-col gap-4">
    <div id="a" style="padding: 12px; background: #1e293b">Bloco A</div>
    <div id="b" style="padding: 12px; background: #334155">Bloco B</div>
  </div>`;

async function setupProject(request: APIRequestContext, page: Page): Promise<string> {
  const email = `tools_${Date.now()}_${Math.random().toString(16).slice(2, 6)}@empresa.com`;
  const reg = await request.post('/api/auth/register', {
    data: { name: 'Tools', email, password: PASSWORD, organization_name: 'Org Tools' },
  });
  expect(reg.ok()).toBeTruthy();
  await page.goto('/');
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'mockbird_csrf')?.value;
  const headers = token ? { 'X-CSRF-Token': token } : {};

  const project = await (await request.post('/api/projects', { data: { name: 'Projeto Tools' }, headers })).json();
  const screens = await (await request.get(`/api/projects/${project.id}/screens`)).json();
  const screen = screens[0];
  const updated = await request.put(`/api/screens/${screen.id}`, {
    data: { name: 'Ferramentas', html_content: SCREEN_HTML, css_content: '', js_content: '' },
    headers,
  });
  expect(updated.ok()).toBeTruthy();
  return project.id;
}

/** Arrasta o elemento com eventos de ponteiro reais dentro do iframe. */
async function dragElement(canvas: FrameLocator, selector: string, dx: number, dy: number) {
  await canvas.locator(selector).evaluate(
    (el, delta) => {
      const rect = el.getBoundingClientRect();
      const base = {
        bubbles: true,
        cancelable: true,
        button: 0,
        pointerId: 1,
        pointerType: 'mouse',
        isPrimary: true,
        // No modo mock o arraste é com Shift (clique simples é ação da página).
        shiftKey: true,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
      };
      el.dispatchEvent(new PointerEvent('pointerdown', base));
      document.dispatchEvent(
        new PointerEvent('pointermove', { ...base, clientX: base.clientX + delta.dx, clientY: base.clientY + delta.dy }),
      );
      document.dispatchEvent(
        new PointerEvent('pointerup', { ...base, clientX: base.clientX + delta.dx, clientY: base.clientY + delta.dy }),
      );
    },
    { dx, dy },
  );
}

test('canvas edita em grupo com Shift e desfaz/refaz', async ({ page, context }) => {
  const projectId = await setupProject(context.request, page);
  await page.goto(`/editor/${projectId}`);

  const canvas = page.frameLocator('iframe[title="Mockbird Canvas"]');
  await expect(canvas.locator('#a')).toHaveText('Bloco A', { timeout: 20_000 });

  // Shift+clique acumula seleção: dois elementos, uma caixa cada.
  await canvas.locator('#a').dispatchEvent('click', { shiftKey: true, bubbles: true });
  await expect(canvas.locator('#a')).toHaveClass(/mb-selected/);
  // Uma seleção única mostra as oito alças de redimensionar.
  await expect(canvas.locator('#mb-overlay .mb-handle')).toHaveCount(8);

  await canvas.locator('#b').dispatchEvent('click', { shiftKey: true, bubbles: true });
  await expect(canvas.locator('#b')).toHaveClass(/mb-selected/);
  await expect(canvas.locator('#mb-overlay .mb-box')).toHaveCount(2);
  await expect(canvas.locator('#mb-overlay .mb-handle')).toHaveCount(0);
  await expect(page.getByText('2 elementos')).toBeVisible();

  // Arrastar um dos selecionados move o grupo inteiro.
  await dragElement(canvas, '#a', 40, 20);
  expect(await canvas.locator('#a').evaluate((el) => `${el.style.left}|${el.style.top}`)).toBe('40px|20px');
  expect(await canvas.locator('#b').evaluate((el) => `${el.style.left}|${el.style.top}`)).toBe('40px|20px');

  // Excluir a seleção e voltar atrás com Desfazer/Refazer.
  await page.getByRole('button', { name: 'Excluir seleção' }).click();
  await expect(canvas.locator('#a')).toHaveCount(0);
  await expect(canvas.locator('#b')).toHaveCount(0);

  await page.getByRole('button', { name: 'Desfazer' }).click();
  await expect(canvas.locator('#a')).toHaveText('Bloco A');
  await expect(canvas.locator('#b')).toHaveText('Bloco B');

  await page.getByRole('button', { name: 'Refazer' }).click();
  await expect(canvas.locator('#a')).toHaveCount(0);

  await page.getByRole('button', { name: 'Desfazer' }).click();
  await expect(canvas.locator('#a')).toHaveText('Bloco A');
});

test('modo Editar seleciona com clique simples e volta a interagir', async ({ page, context }) => {
  const projectId = await setupProject(context.request, page);
  await page.goto(`/editor/${projectId}`);

  const canvas = page.frameLocator('iframe[title="Mockbird Canvas"]');
  await expect(canvas.locator('#a')).toHaveText('Bloco A', { timeout: 20_000 });

  // No modo mock, clique simples não seleciona.
  await canvas.locator('#a').dispatchEvent('click');
  await expect(canvas.locator('.mb-selected')).toHaveCount(0);

  // Em Editar, clique simples seleciona e libera arraste/alças.
  await page.getByRole('button', { name: 'Editar' }).click();
  await canvas.locator('#a').dispatchEvent('click');
  await expect(canvas.locator('#a')).toHaveClass(/mb-selected/);
  await expect(canvas.locator('#mb-overlay .mb-handle')).toHaveCount(8);

  // Arrastar a alça leste redimensiona o elemento selecionado.
  const widthBefore = await canvas.locator('#a').evaluate((el) => el.getBoundingClientRect().width);
  await canvas.locator('#mb-overlay .mb-handle[data-dir="e"]').evaluate((handle) => {
    const rect = handle.getBoundingClientRect();
    const base = {
      bubbles: true,
      cancelable: true,
      button: 0,
      pointerId: 1,
      pointerType: 'mouse',
      isPrimary: true,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    handle.dispatchEvent(new PointerEvent('pointerdown', base));
    document.dispatchEvent(new PointerEvent('pointermove', { ...base, clientX: base.clientX + 60 }));
    document.dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: base.clientX + 60 }));
  });
  const widthAfter = await canvas.locator('#a').evaluate((el) => el.getBoundingClientRect().width);
  expect(widthAfter).toBeGreaterThan(widthBefore + 50);

  // Shift+clique continua acumulando no modo edição.
  await canvas.locator('#b').dispatchEvent('click', { shiftKey: true, bubbles: true });
  await expect(page.getByText('2 elementos')).toBeVisible();
});
