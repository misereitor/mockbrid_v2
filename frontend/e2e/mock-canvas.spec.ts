import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const PASSWORD = 'SenhaForte123!';

async function register(request: APIRequestContext, prefix: string) {
  const email = `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 6)}@empresa.com`;
  const res = await request.post('/api/auth/register', {
    data: {
      name: 'Usuário Mock',
      email,
      password: PASSWORD,
      organization_name: `Org Mock ${prefix}`,
    },
  });
  expect(res.ok()).toBeTruthy();
}

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'mockbird_csrf')?.value;
  return token ? { 'X-CSRF-Token': token } : {};
}

test('canvas é navegável como mock e Shift+clique seleciona', async ({ page, context }) => {
  await register(context.request, 'mock');
  await page.goto('/');
  const headers = await csrf(page);

  const project = await (
    await context.request.post('/api/projects', { data: { name: 'Projeto Mock' }, headers })
  ).json();
  const screens = await (await context.request.get(`/api/projects/${project.id}/screens`)).json();
  const home = screens[0];

  const cadastro = await (
    await context.request.post('/api/screens', {
      data: {
        canvas_id: home.canvas_id,
        name: 'Cadastro',
        width: 1440,
        height: 900,
        html_content: `
          <div class="p-8">
            <h1 id="cadastro" style="font-size: 32px">Cadastro Mock</h1>
            <button id="voltar" data-go="home.html" style="margin-top: 16px">Voltar</button>
          </div>`,
      },
      headers,
    })
  ).json();

  const homeUpdate = await context.request.put(`/api/screens/${home.id}`, {
    data: {
      name: 'Home',
      html_content: `
        <div class="p-8">
          <h1 id="titulo" style="font-size: 32px">Home Mock</h1>
          <a id="criar-conta" href="02-cadastro.html" style="color: #0f766e">Criar conta</a>
        </div>`,
      css_content: '',
      js_content: '',
    },
    headers,
  });
  expect(homeUpdate.ok()).toBeTruthy();
  expect(cadastro.id).toBeTruthy();

  await page.goto(`/editor/${project.id}`);
  const canvas = page.frameLocator('iframe[title="Mockbird Canvas"]');
  await expect(canvas.getByText('Home Mock')).toBeVisible({ timeout: 20_000 });

  // O artboard é escalado por CSS transform, e o hit-test do Playwright não
  // atravessa essa escala dentro do iframe; os cliques são disparados no frame,
  // o que exercita exatamente os mesmos handlers do runtime.
  await canvas.locator('#titulo').dispatchEvent('click');
  await expect(canvas.locator('.mb-selected')).toHaveCount(0);

  // Shift+clique seleciona o elemento para edição.
  await canvas.locator('#titulo').dispatchEvent('click', { shiftKey: true, bubbles: true });
  await expect(canvas.locator('#titulo')).toHaveClass(/mb-selected/);

  // Clique normal em link interno troca de tela em vez de navegar o iframe.
  await canvas.locator('#criar-conta').dispatchEvent('click');
  await expect(page.getByRole('tab', { name: 'Cadastro' })).toHaveAttribute('aria-selected', 'true');
  await expect(canvas.getByText('Cadastro Mock')).toBeVisible();

  // data-go também navega (e casa pelo nome da tela, sem o prefixo numérico).
  await canvas.locator('#voltar').dispatchEvent('click');
  await expect(page.getByRole('tab', { name: 'Home' })).toHaveAttribute('aria-selected', 'true');
  await expect(canvas.getByText('Home Mock')).toBeVisible();
});
