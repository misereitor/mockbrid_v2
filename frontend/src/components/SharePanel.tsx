/**
 * Painel Compartilhar: links de apresentação de um projeto.
 *
 * Cada link tem URL própria (token aleatório) e permissões editáveis sem trocar a
 * URL: nível de acesso, senha, validade, comentários de visitantes e rótulo.
 * Revogar derruba o acesso na hora.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Check, Copy, ExternalLink, Globe, Link2, Lock, Pencil, Trash2, X } from 'lucide-react';
import { withBasePath } from '../lib/basePath';
import { copyToClipboard } from '../lib/clipboard';

export interface ShareLink {
  id: string;
  project_id: string;
  slug: string;
  allow_comments: boolean;
  access_mode: 'anyone' | 'org';
  label: string | null;
  expires_at: string | null;
  view_count: number;
  has_password: boolean;
  created_at: string;
}

interface SharePanelProps {
  projectId: string;
  projectName: string;
  onClose: () => void;
}

type AccessMode = 'anyone' | 'org';

const ACCESS_LABEL: Record<AccessMode, string> = {
  anyone: 'Qualquer pessoa com o link',
  org: 'Só membros da organização',
};

const EXPIRY_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: 'Sem validade' },
  { value: 7, label: '7 dias' },
  { value: 30, label: '30 dias' },
  { value: 90, label: '90 dias' },
];

function shareUrl(slug: string): string {
  return `${window.location.origin}${withBasePath(`/p/${slug}`)}`;
}

function formatDate(value: string | null): string {
  if (!value) return 'Sem validade';
  return new Date(value).toLocaleDateString('pt-BR');
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (typeof body?.detail?.message === 'string') return body.detail.message;
  } catch {
    /* sem corpo JSON */
  }
  return 'Não foi possível concluir a ação';
}

function csrfHeader(): Record<string, string> {
  const match = document.cookie.split('; ').find((c) => c.startsWith('mockbird_csrf='));
  return match ? { 'X-CSRF-Token': decodeURIComponent(match.split('=')[1] || '') } : {};
}

export function SharePanel({ projectId, projectName, onClose }: SharePanelProps) {
  const base = `/api/projects/${projectId}/share-links`;
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copySuccessMsg, setCopySuccessMsg] = useState<string | null>(null);

  // Formulário de criação
  const [accessMode, setAccessMode] = useState<AccessMode>('anyone');
  const [usePassword, setUsePassword] = useState(false);
  const [password, setPassword] = useState('');
  const [expiryDays, setExpiryDays] = useState(90);
  const [allowComments, setAllowComments] = useState(false);
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);

  // Edição de um link existente (só o rótulo e a senha; o resto fica no card)
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editPassword, setEditPassword] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(base, { credentials: 'same-origin' });
      if (!res.ok) throw new Error(await readError(res));
      setLinks(await res.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar links');
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    load();
  }, [load]);

  const patchLink = async (id: string, body: Record<string, unknown>): Promise<boolean> => {
    setError(null);
    const res = await fetch(`${base}/${id}`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      setError(await readError(res));
      return false;
    }
    const updated: ShareLink = await res.json();
    setLinks((prev) => prev.map((l) => (l.id === id ? updated : l)));
    return true;
  };

  const createLink = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const res = await fetch(base, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...csrfHeader() },
        body: JSON.stringify({
          access_mode: accessMode,
          allow_comments: allowComments,
          expires_in_days: expiryDays,
          password: usePassword && accessMode === 'anyone' ? password : '',
          label: label.trim() || null,
        }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const created: ShareLink = await res.json();
      setLinks((prev) => [created, ...prev]);
      setPassword('');
      setLabel('');
      setUsePassword(false);
      // Já copia a URL do link novo: é o que o usuário quer fazer logo em seguida.
      await copyUrl(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível criar o link');
    } finally {
      setCreating(false);
    }
  };

  const copyUrl = async (link: ShareLink) => {
    setError(null);
    const url = shareUrl(link.slug);
    const ok = await copyToClipboard(url);
    if (ok) {
      setCopiedId(link.id);
      setCopySuccessMsg('Link copiado para a área de transferência!');
      setTimeout(() => {
        setCopiedId((current) => (current === link.id ? null : current));
        setCopySuccessMsg((cur) => (cur === 'Link copiado para a área de transferência!' ? null : cur));
      }, 3000);
    } else {
      setError('Não foi possível copiar automaticamente no navegador. Selecione o endereço no campo abaixo e copie com Ctrl+C.');
    }
  };

  const revoke = async (link: ShareLink) => {
    if (!window.confirm('Revogar este link? Quem tiver o endereço perde o acesso na hora.')) return;
    setError(null);
    const res = await fetch(`${base}/${link.id}`, {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: csrfHeader(),
    });
    if (!res.ok) {
      setError(await readError(res));
      return;
    }
    setLinks((prev) => prev.filter((l) => l.id !== link.id));
  };

  const saveEdit = async (link: ShareLink) => {
    const body: Record<string, unknown> = { label: editLabel.trim() || null };
    if (editPassword) body.password = editPassword;
    if (await patchLink(link.id, body)) {
      setEditingId(null);
      setEditPassword('');
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-panel-title"
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-6"
      >
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-xl bg-mockbird-blue/10 text-mockbird-cyan border border-mockbird-blue/20 flex items-center justify-center">
              <Link2 className="h-5 w-5" />
            </div>
            <div>
              <h3 id="share-panel-title" className="font-bold text-base text-white">Compartilhar</h3>
              <p className="text-xs text-slate-400">Links de apresentação de {projectName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X size={18} />
          </button>
        </div>

        {copySuccessMsg && (
          <div role="status" className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-2 flex items-center gap-2">
            <Check size={14} className="text-emerald-400 shrink-0" />
            <span>{copySuccessMsg}</span>
          </div>
        )}

        {error && (
          <div role="alert" className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* Criação */}
        <form onSubmit={createLink} className="space-y-4 rounded-2xl border border-slate-800 p-4">
          <p className="text-sm font-semibold text-white">Novo link</p>

          <fieldset className="space-y-2">
            <legend className="mb-label mb-2">Quem pode abrir</legend>
            {(Object.keys(ACCESS_LABEL) as AccessMode[]).map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
                <input
                  type="radio"
                  name="access_mode"
                  checked={accessMode === mode}
                  onChange={() => setAccessMode(mode)}
                />
                {mode === 'anyone' ? <Globe size={14} className="text-slate-400" /> : <Lock size={14} className="text-slate-400" />}
                {ACCESS_LABEL[mode]}
              </label>
            ))}
            {accessMode === 'org' && (
              <p className="text-[11px] text-slate-500">
                Quem não for membro da organização vê "Apresentação não encontrada".
              </p>
            )}
          </fieldset>

          {accessMode === 'anyone' && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
                <input type="checkbox" checked={usePassword} onChange={(e) => setUsePassword(e.target.checked)} />
                Exigir senha
              </label>
              {usePassword && (
                <input
                  type="password"
                  className="mb-input"
                  placeholder="Senha de acesso (mín. 6 caracteres)"
                  minLength={6}
                  maxLength={128}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="mb-label">Validade</span>
              <select className="mb-input" value={expiryDays} onChange={(e) => setExpiryDays(Number(e.target.value))}>
                {EXPIRY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="mb-label">Nome do link (opcional)</span>
              <input
                className="mb-input"
                placeholder="Ex.: Diretoria"
                maxLength={120}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
            <input type="checkbox" checked={allowComments} onChange={(e) => setAllowComments(e.target.checked)} />
            Permitir comentários de visitantes
          </label>

          <div className="flex justify-end">
            <button type="submit" disabled={creating || (usePassword && accessMode === 'anyone' && password.length < 6)} className="mb-btn-primary">
              <Link2 size={14} /> {creating ? 'Criando…' : 'Criar e copiar link'}
            </button>
          </div>
        </form>

        {/* Lista */}
        <div className="space-y-3">
          <p className="text-sm font-semibold text-white">Links existentes</p>

          {loading && <p className="text-xs text-slate-400">Carregando…</p>}

          {!loading && links.length === 0 && (
            <p className="text-xs text-slate-400 rounded-xl border border-dashed border-slate-700 p-4 text-center">
              Este projeto não está compartilhado. Crie um link acima para enviar a apresentação.
            </p>
          )}

          {links.map((link) => {
            const expired = link.expires_at && new Date(link.expires_at) < new Date();
            return (
              <div key={link.id} className="rounded-xl border border-slate-800 p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-white truncate">{link.label || 'Link sem nome'}</p>
                    <div className="mt-1 flex items-center gap-2 bg-slate-950/70 border border-slate-800 rounded-lg px-2.5 py-1.5">
                      <input
                        type="text"
                        readOnly
                        value={shareUrl(link.slug)}
                        onClick={(e) => (e.target as HTMLInputElement).select()}
                        className="bg-transparent text-xs text-slate-300 font-mono flex-1 outline-none truncate selection:bg-mockbird-blue selection:text-white cursor-pointer"
                        title="Clique para selecionar o link completo"
                      />
                      <button
                        type="button"
                        onClick={() => copyUrl(link)}
                        className={`px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition ${
                          copiedId === link.id
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'bg-mockbird-blue/20 hover:bg-mockbird-blue/30 text-mockbird-cyan border border-mockbird-blue/30'
                        }`}
                        title="Copiar link"
                      >
                        {copiedId === link.id ? (
                          <>
                            <Check size={13} className="text-emerald-400" />
                            <span>Copiado!</span>
                          </>
                        ) : (
                          <>
                            <Copy size={13} />
                            <span>Copiar</span>
                          </>
                        )}
                      </button>
                      <a
                        href={shareUrl(link.slug)}
                        target="_blank"
                        rel="noreferrer"
                        className="px-2 py-1 rounded text-xs text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-700/60 flex items-center gap-1 transition"
                        title="Abrir apresentação em nova aba"
                      >
                        <ExternalLink size={13} />
                        <span className="hidden sm:inline">Abrir</span>
                      </a>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 pt-0.5">
                    <button
                      onClick={() => {
                        setEditingId(editingId === link.id ? null : link.id);
                        setEditLabel(link.label || '');
                        setEditPassword('');
                      }}
                      className="mb-btn-ghost !p-1.5"
                      aria-label="Editar link"
                      title="Editar"
                    >
                      <Pencil size={14} />
                    </button>
                    <button onClick={() => revoke(link)} className="mb-btn-ghost !p-1.5 text-rose-400 hover:text-rose-300" aria-label="Revogar link" title="Revogar">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 text-[11px]">
                  <span className="px-2 py-0.5 rounded-full border border-slate-700 text-slate-300">
                    {ACCESS_LABEL[link.access_mode] ?? link.access_mode}
                  </span>
                  <span className="px-2 py-0.5 rounded-full border border-slate-700 text-slate-300">
                    {link.has_password ? 'Com senha' : 'Sem senha'}
                  </span>
                  <span className={`px-2 py-0.5 rounded-full border ${expired ? 'border-rose-500/40 text-rose-300' : 'border-slate-700 text-slate-300'}`}>
                    {expired ? 'Expirado' : `Validade: ${formatDate(link.expires_at)}`}
                  </span>
                  <span className="px-2 py-0.5 rounded-full border border-slate-700 text-slate-300">
                    {link.allow_comments ? 'Comentários ligados' : 'Sem comentários'}
                  </span>
                  <span className="px-2 py-0.5 rounded-full border border-slate-700 text-slate-400">
                    {link.view_count} visualizações
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <select
                    className="mb-input !w-auto"
                    aria-label="Quem pode abrir"
                    value={link.access_mode}
                    onChange={(e) => patchLink(link.id, { access_mode: e.target.value })}
                  >
                    <option value="anyone">Qualquer pessoa com o link</option>
                    <option value="org">Só membros da organização</option>
                  </select>
                  <label className="flex items-center gap-1.5 text-xs text-slate-300">
                    <input
                      type="checkbox"
                      checked={link.allow_comments}
                      onChange={(e) => patchLink(link.id, { allow_comments: e.target.checked })}
                    />
                    Comentários
                  </label>
                  <select
                    className="mb-input !w-auto"
                    aria-label="Validade"
                    value=""
                    onChange={(e) => {
                      if (e.target.value !== '') {
                        patchLink(link.id, { expires_in_days: Number(e.target.value) });
                      }
                    }}
                  >
                    <option value="" disabled>
                      Alterar validade…
                    </option>
                    {EXPIRY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.value === 0 ? 'Sem validade' : `Renovar por ${o.label}`}
                      </option>
                    ))}
                  </select>
                  {link.has_password && (
                    <button onClick={() => patchLink(link.id, { password: '' })} className="mb-btn-outline">
                      Remover senha
                    </button>
                  )}
                </div>

                {editingId === link.id && (
                  <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-800">
                    <label className="space-y-1">
                      <span className="mb-label">Nome do link</span>
                      <input className="mb-input" maxLength={120} value={editLabel} onChange={(e) => setEditLabel(e.target.value)} />
                    </label>
                    <label className="space-y-1">
                      <span className="mb-label">Nova senha (deixe vazio para manter)</span>
                      <input
                        type="password"
                        className="mb-input"
                        minLength={6}
                        maxLength={128}
                        value={editPassword}
                        onChange={(e) => setEditPassword(e.target.value)}
                      />
                    </label>
                    <div className="col-span-2 flex justify-end gap-2">
                      <button onClick={() => setEditingId(null)} className="mb-btn-outline">Cancelar</button>
                      <button onClick={() => saveEdit(link)} className="mb-btn-primary">Salvar</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
