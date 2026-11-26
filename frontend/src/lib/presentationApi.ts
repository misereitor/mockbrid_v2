/**
 * Cliente da apresentação (link público e pré-visualização privada).
 *
 * A senha de um share link vai no cabeçalho `X-Share-Password`, nunca na URL:
 * na query string ela aparece em logs e no histórico do navegador.
 */
import { withBasePath } from './basePath';

export type PresentationErrorCode =
  | 'not_found'
  | 'expired'
  | 'login_required'
  | 'password_required'
  | 'password_invalid'
  | 'unknown';

export class PresentationError extends Error {
  code: PresentationErrorCode;
  status: number;

  constructor(code: PresentationErrorCode, status: number, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/** Lê o erro estruturado da API ({detail: {code, message}}) ou cai para o status. */
async function toPresentationError(res: Response): Promise<PresentationError> {
  let code: PresentationErrorCode = 'unknown';
  let message = 'Não foi possível abrir a apresentação';
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (detail && typeof detail === 'object') {
      if (typeof detail.code === 'string') code = detail.code as PresentationErrorCode;
      if (typeof detail.message === 'string') message = detail.message;
    } else if (typeof detail === 'string') {
      message = detail;
    }
  } catch {
    /* corpo que não é JSON: mantém a mensagem padrão */
  }
  if (code === 'unknown') {
    if (res.status === 404) code = 'not_found';
    if (res.status === 410) code = 'expired';
  }
  return new PresentationError(code, res.status, message);
}

function passwordHeaders(password?: string): Record<string, string> {
  return password ? { 'X-Share-Password': password } : {};
}

/** Carrega a apresentação pelo token do share link. Lança PresentationError. */
export async function fetchPublicPresentation(slug: string, password?: string): Promise<any> {
  const res = await fetch(withBasePath(`/api/public/p/${encodeURIComponent(slug)}`), {
    headers: passwordHeaders(password),
    credentials: 'same-origin',
  });
  if (!res.ok) throw await toPresentationError(res);
  return res.json();
}

/** Pré-visualização privada do projeto (exige sessão com acesso ao projeto). */
export async function fetchPrivatePresentation(projectId: string): Promise<any> {
  const res = await fetch(withBasePath(`/api/projects/${encodeURIComponent(projectId)}/presentation`), {
    credentials: 'same-origin',
  });
  if (!res.ok) throw await toPresentationError(res);
  return res.json();
}

export async function fetchGuestComments(slug: string, screenId: string, password?: string): Promise<Response> {
  return fetch(
    withBasePath(`/api/public/p/${encodeURIComponent(slug)}/comments?screen_id=${encodeURIComponent(screenId)}`),
    { headers: passwordHeaders(password), credentials: 'same-origin' },
  );
}

export async function postGuestComment(
  slug: string,
  payload: Record<string, unknown>,
  password?: string,
): Promise<Response> {
  return fetch(withBasePath(`/api/public/p/${encodeURIComponent(slug)}/comments`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...passwordHeaders(password) },
    credentials: 'same-origin',
    body: JSON.stringify(payload),
  });
}

/** Mensagem curta para o usuário a partir do código de erro. */
export function presentationErrorMessage(err: PresentationError): string {
  switch (err.code) {
    case 'password_invalid':
      return 'Senha incorreta.';
    case 'not_found':
      return 'Apresentação não encontrada ou sem acesso.';
    case 'expired':
      return 'Este link de apresentação expirou.';
    default:
      return err.message;
  }
}
