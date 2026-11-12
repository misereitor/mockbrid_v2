import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const PASSWORD = 'SenhaForte123!';

async function register(request: APIRequestContext, prefix: string) {
  const email = `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 6)}@empresa.com`;
  const res = await request.post('/api/auth/register', {
    data: {
      name: 'Usuário E2E',
      email,
      password: PASSWORD,
      organization_name: `Org E2E ${prefix}`,
    },
  });
  expect(res.ok()).toBeTruthy();
  return email;
}

async function csrf(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'mockbird_csrf')?.value;
  return token ? { 'X-CSRF-Token': token } : {};
}

async function createProject(page: Page, name: string): Promise<any> {
  const res = await page.context().request.post('/api/projects', {
    data: { name },
    headers: await csrf(page),
  });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

test('registro, projeto e editor carregam no navegador', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Bem-vindo de volta' })).toBeVisible();

  await page.getByRole('button', { name: 'Criar conta' }).click();
  await page.getByLabel('Seu nome').fill('Usuário E2E');
  await page.getByLabel('Nome da organização').fill('Org Navegador');
  await page.getByLabel('E-mail').fill(`ui_${Date.now()}@empresa.com`);
  await page.getByLabel('Senha').fill(PASSWORD);
  await page.getByRole('button', { name: 'Criar conta' }).last().click();

  await expect(page.getByRole('button', { name: 'Novo projeto' })).toBeVisible();

  await page.getByRole('button', { name: 'Novo projeto' }).click();
  await page.locator('#proj-name').fill('Projeto E2E');
  await page
    .locator('form')
    .filter({ has: page.locator('#proj-name') })
    .getByRole('button', { name: 'Criar projeto' })
    .click();

  await expect(page.getByRole('button', { name: /Salvar/ })).toBeVisible();
  await page.waitForURL(/\/editor\//);
});

test('presença em tempo real aparece ao abrir o mesmo projeto em outra aba', async ({ page, context }) => {
  await register(context.request, 'presence');
  await page.goto('/');
  const project = await createProject(page, 'Projeto Presença');

  await page.goto(`/editor/${project.id}`);
  await expect(page.getByRole('button', { name: /Salvar/ })).toBeVisible();

  const secondPage = await context.newPage();
  await secondPage.goto(`/editor/${project.id}`);
  await expect(secondPage.getByRole('button', { name: /Salvar/ })).toBeVisible();

  await expect(page.getByTitle('Pessoas neste projeto agora')).toBeVisible();
  await expect(secondPage.getByTitle('Pessoas neste projeto agora')).toBeVisible();
});

test('link de apresentação abre e aceita comentário de visitante', async ({ page, context }) => {
  await register(context.request, 'share');
  await page.goto('/');
  const project = await createProject(page, 'Projeto Apresentação');

  const linkRes = await context.request.post(`/api/projects/${project.id}/share-links`, {
    data: { allow_comments: true },
    headers: await csrf(page),
  });
  expect(linkRes.ok()).toBeTruthy();
  const link = await linkRes.json();

  const guest = await context.newPage();
  await guest.goto(`/p/${link.slug}`);
  await expect(guest.getByText('Modo Apresentação')).toBeVisible();

  await guest.getByRole('button', { name: /Comentar/ }).click();
  await guest.getByPlaceholder('Seu nome (opcional)').fill('Visitante CEO');
  await guest.getByPlaceholder(/Deixe um comentário/).fill('Ajustar o espaçamento do header.');
  await guest.getByRole('button', { name: /Enviar comentário/ }).click();

  await expect(guest.getByText('Ajustar o espaçamento do header.')).toBeVisible();
  await expect(guest.getByText('Visitante CEO')).toBeVisible();
});
