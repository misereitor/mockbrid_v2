/**
 * Utilitário para suportar execução tanto na raiz (/) quanto sob subpath
 * em proxy reverso Nginx (ex: https://tradit.ddns.net/mockbrid).
 */

export function getBasePath(): string {
  if (typeof window === 'undefined') return '';
  const path = window.location.pathname;
  if (path === '/mockbrid' || path.startsWith('/mockbrid/')) return '/mockbrid';
  if (path === '/mockbird' || path.startsWith('/mockbird/')) return '/mockbird';
  return '';
}

export function stripBasePath(pathname: string): string {
  const base = getBasePath();
  if (base && (pathname === base || pathname.startsWith(base + '/'))) {
    return pathname.slice(base.length) || '/';
  }
  return pathname || '/';
}

export function withBasePath(path: string): string {
  const base = getBasePath();
  if (!base) return path;
  if (!path.startsWith('/')) return `${base}/${path}`;
  if (path === base || path.startsWith(base + '/')) return path;
  return path === '/' ? `${base}/` : `${base}${path}`;
}
