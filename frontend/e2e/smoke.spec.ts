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

test('Apresentar é só pré-visualização: não cria nenhum link público', async ({ page, context }) => {
  await register(context.request, 'preview');
  await page.goto('/');
  const project = await createProject(page, 'Projeto Preview');

  const before = await context.request.get(`/api/projects/${project.id}/share-links`);
  expect((await before.json()).length).toBe(0);

  await page.goto(`/editor/${project.id}`);
  // Mesma aba, como antes: a pré-visualização troca a rota, não publica nada.
  await page.getByRole('button', { name: /Apresentar/ }).click();
  await expect(page).toHaveURL(new RegExp(`/preview/${project.id}$`));
  await expect(page.getByText('Modo Apresentação')).toBeVisible();

  // Nenhum link foi criado e o slug do projeto não abre a apresentação pública.
  const after = await context.request.get(`/api/projects/${project.id}/share-links`);
  expect((await after.json()).length).toBe(0);
  const slugAttempt = await context.request.get(`/api/public/p/${project.slug}`);
  expect(slugAttempt.status()).toBe(404);
});

test('painel Compartilhar cria link, altera permissão e revoga', async ({ page, context }) => {
  await register(context.request, 'sharepanel');
  await page.goto('/');
  const project = await createProject(page, 'Projeto Painel');

  await page.goto(`/editor/${project.id}`);
  await page.getByRole('button', { name: /Compartilhar/ }).click();
  await expect(page.getByText('Este projeto não está compartilhado')).toBeVisible();

  await page.getByRole('button', { name: /Criar e copiar link/ }).click();
  await expect(page.getByText('Qualquer pessoa com o link').first()).toBeVisible();

  const listed = await (await context.request.get(`/api/projects/${project.id}/share-links`)).json();
  expect(listed.length).toBe(1);
  const link = listed[0];

  // Muda de "qualquer pessoa" para "só organização" sem trocar a URL.
  await page.getByRole('combobox', { name: 'Quem pode abrir' }).selectOption('org');
  await expect(page.getByText('Só membros da organização').first()).toBeVisible();

  // Visitante sem login é levado ao login e o link fica guardado para voltar depois.
  const guest = await context.browser()!.newContext();
  const guestPage = await guest.newPage();
  await guestPage.goto(`/p/${link.slug}`);
  await expect(guestPage).toHaveURL(/\/login$/);
  await expect(guestPage.getByText('Bem-vindo de volta')).toBeVisible();
  expect(await guestPage.evaluate(() => sessionStorage.getItem('mockbird_return_to'))).toBe(`/p/${link.slug}`);
  await guest.close();

  // Revoga: o link deixa de existir.
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Revogar link' }).click();
  await expect(page.getByText('Este projeto não está compartilhado')).toBeVisible();
  const gone = await context.request.get(`/api/public/p/${link.slug}`);
  expect(gone.status()).toBe(404);
});

test('link com senha pede senha no navegador e aceita a correta', async ({ page, context }) => {
  await register(context.request, 'pwdlink');
  await page.goto('/');
  const project = await createProject(page, 'Projeto Senha');

  const linkRes = await context.request.post(`/api/projects/${project.id}/share-links`, {
    data: { password: 'segredo123', allow_comments: false },
    headers: await csrf(page),
  });
  const link = await linkRes.json();

  const guest = await context.browser()!.newContext();
  const guestPage = await guest.newPage();
  await guestPage.goto(`/p/${link.slug}`);
  await expect(guestPage.getByText('Apresentação protegida')).toBeVisible();

  await guestPage.getByPlaceholder('Senha de acesso').fill('errada');
  await guestPage.getByRole('button', { name: 'Abrir apresentação' }).click();
  await expect(guestPage.getByText('Senha incorreta.')).toBeVisible();

  await guestPage.getByPlaceholder('Senha de acesso').fill('segredo123');
  await guestPage.getByRole('button', { name: 'Abrir apresentação' }).click();
  await expect(guestPage.getByText('Modo Apresentação')).toBeVisible();
  await guest.close();
});
