/**
 * Apresentação de um projeto.
 *
 * "Apresentar" abre a pré-visualização privada (`/preview/:id`): não cria nem
 * altera nenhum link público. Compartilhar com outras pessoas é uma ação
 * separada, feita no painel Compartilhar (share links com senha, validade e
 * nível de acesso).
 */
import { withBasePath } from './basePath';

export function previewPath(projectId: string): string {
  return withBasePath(`/preview/${encodeURIComponent(projectId)}`);
}

export function openPresentation(projectId: string): void {
  window.open(previewPath(projectId), '_blank', 'noreferrer');
}
