/** Upload de imagens para o projeto e montagem do HTML de inserção. */

export interface ProjectAsset {
  id: string;
  project_id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  url: string;
}

export async function uploadProjectAsset(projectId: string, file: File): Promise<ProjectAsset> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api/projects/${projectId}/assets`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    let detail = 'Falha no upload da imagem';
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function listProjectAssets(projectId: string): Promise<ProjectAsset[]> {
  const res = await fetch(`/api/projects/${projectId}/assets`);
  if (!res.ok) return [];
  return res.json();
}

export async function deleteProjectAsset(projectId: string, assetId: string): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/assets/${assetId}`, { method: 'DELETE' });
  if (!res.ok) {
    let detail = 'Falha ao remover asset';
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}

export async function getBrokenImages(projectId: string): Promise<string[]> {
  const res = await fetch(`/api/projects/${projectId}/broken-images`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.broken_urls || [];
}

export async function replaceAssetUrls(
  projectId: string,
  oldUrl: string,
  assetId: string
): Promise<{ replaced_screens: number; new_url: string; message?: string }> {
  const res = await fetch(`/api/projects/${projectId}/replace-asset-urls`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old_url: oldUrl, asset_id: assetId }),
  });
  if (!res.ok) {
    let detail = 'Falha ao substituir caminho do asset';
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function imageHtml(asset: ProjectAsset): string {
  const safeName = asset.original_name.replace(/[^\w.\- ]/g, '');
  return `<img src="${asset.url}" alt="${safeName}" style="max-width:100%;height:auto;" />`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
