/**
 * Resolve o destino de um clique no mock para uma tela do projeto.
 *
 * Aceita o que aparece no HTML: `02-cadastro.html`, `cadastro.html`,
 * `../login/01-login.html`, `#/cadastro` ou o nome da tela. O prefixo numérico
 * dos arquivos do corpus v1 (`02-`) é ignorado, então `02-cadastro.html` casa
 * com a tela "Cadastro".
 */

export interface NavScreen {
  id: string;
  name: string;
  slug?: string;
}

/** Normaliza um alvo/nome para comparação. */
export function screenKey(value: string): string {
  let raw = String(value || '').trim();
  if (!raw) return '';
  // Se começar com #/ ou #, limpa o prefixo de rota SPA
  raw = raw.replace(/^#\/?/, '');
  // Separa query params e fragmentos adicionais
  raw = raw.split('?')[0].split('#')[0];
  raw = raw.replace(/\\/g, '/');
  raw = raw.split('/').filter(Boolean).pop() || raw;
  raw = raw.replace(/\.html?$/i, '');
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* mantém o valor original */
  }
  return raw
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/^\d+[\s._-]*/, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Índice da tela correspondente ao alvo, ou -1. */
export function resolveScreenIndex(target: string, screens: NavScreen[]): number {
  const key = screenKey(target);
  if (!key) return -1;

  const byId = screens.findIndex((screen) => screen.id === target.trim());
  if (byId >= 0) return byId;

  const bySlug = screens.findIndex((screen) => screen.slug && screenKey(screen.slug) === key);
  if (bySlug >= 0) return bySlug;

  const keys = screens.map((screen) => screenKey(screen.name));
  const exact = keys.indexOf(key);
  if (exact >= 0) return exact;

  return keys.findIndex(
    (candidate) => candidate.length >= 3 && (candidate.includes(key) || key.includes(candidate)),
  );
}
