/** Publica o projeto (idempotente) e devolve o slug público de apresentação. */

function csrfHeader(): Record<string, string> {
  const match = document.cookie.split('; ').find((c) => c.startsWith('mockbird_csrf='));
  return match ? { 'X-CSRF-Token': decodeURIComponent(match.split('=')[1] || '') } : {};
}

export async function ensurePublished(projectId: string): Promise<string> {
  const res = await fetch(`/api/projects/${projectId}/publish`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeader(),
  });
  if (!res.ok) {
    throw new Error('Não foi possível habilitar o link de apresentação');
  }
  const data = await res.json();
  return data.slug as string;
}

export async function openPresentation(projectId: string): Promise<void> {
  const slug = await ensurePublished(projectId);
  window.open(`/p/${slug}`, '_blank', 'noreferrer');
}

export async function copyPresentationLink(projectId: string): Promise<string> {
  const slug = await ensurePublished(projectId);
  const url = `${window.location.origin}/p/${slug}`;
  await navigator.clipboard.writeText(url);
  return slug;
}
