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

export function imageHtml(asset: ProjectAsset): string {
  const safeName = asset.original_name.replace(/[^\w.\- ]/g, '');
  return `<img src="${asset.url}" alt="${safeName}" style="max-width:100%;height:auto;" />`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
