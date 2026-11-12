import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { ArrowLeft, Bell, Lock, MessageSquare, Send, X } from 'lucide-react';

interface GuestComment {
  id: string;
  screen_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

interface PresentationPageProps {
  slug: string;
  onBackToApp?: () => void;
}

export const PresentationPage: React.FC<PresentationPageProps> = ({ slug, onBackToApp }) => {
  const [projectData, setProjectData] = useState<any>(null);
  const [currentScreenIndex, setCurrentScreenIndex] = useState(0);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [needsPassword, setNeedsPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Comentários de visitantes (share links com allow_comments)
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [comments, setComments] = useState<GuestComment[]>([]);
  const [guestName, setGuestName] = useState('');
  const [commentBody, setCommentBody] = useState('');
  const [commentError, setCommentError] = useState<string | null>(null);
  const [sendingComment, setSendingComment] = useState(false);

  const loadPresentation = useCallback((pwd?: string) => {
    setLoading(true);
    const query = pwd ? `?password=${encodeURIComponent(pwd)}` : '';
    return fetch(`/api/public/p/${slug}${query}`)
      .then(async r => {
        if (r.status === 401 || r.status === 403) {
          setNeedsPassword(true);
          setPasswordError(r.status === 403 ? 'Senha incorreta.' : null);
          setLoading(false);
          return null;
        }
        if (!r.ok) throw new Error('Projeto de apresentação não encontrado');
        return r.json();
      })
      .then(d => {
        if (!d) return;
        setNeedsPassword(false);
        setProjectData(d);
        // Encontra tela principal se houver
        if (d.screens && d.screens.length > 0) {
          const mainIdx = d.screens.findIndex((s: any) => s.is_main);
          if (mainIdx >= 0) setCurrentScreenIndex(mainIdx);
        }
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    loadPresentation();
  }, [loadPresentation]);

  // Listener para eventos interativos no iframe
  useEffect(() => {
    const handleMsg = (ev: MessageEvent) => {
      if (ev.source !== iframeRef.current?.contentWindow) return;
      if (ev.data?.type === 'MOCK_TOAST') {
        setToastMessage(ev.data.message);
        setTimeout(() => setToastMessage(null), 3500);
      }
    };
    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, []);

  // Injeta HTML e scripts interativos na tela do CEO
  const activeScreen = projectData?.screens?.[currentScreenIndex];
  const tokens = projectData?.tokens || {};
  const commentsEnabled = Boolean(projectData?.allow_comments);
  const screenId = activeScreen?.id as string | undefined;

  const loadComments = useCallback(async () => {
    if (!commentsEnabled || !screenId) return;
    const pwdQuery = password ? `&password=${encodeURIComponent(password)}` : '';
    try {
      const res = await fetch(`/api/public/p/${slug}/comments?screen_id=${screenId}${pwdQuery}`);
      if (res.ok) setComments(await res.json());
    } catch (err) {
      console.error('Erro ao carregar comentários:', err);
    }
  }, [commentsEnabled, screenId, slug, password]);

  useEffect(() => {
    loadComments();
  }, [loadComments]);

  const submitGuestComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!screenId || !commentBody.trim() || sendingComment) return;
    setSendingComment(true);
    setCommentError(null);
    try {
      const pwdQuery = password ? `?password=${encodeURIComponent(password)}` : '';
      const res = await fetch(`/api/public/p/${slug}/comments${pwdQuery}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          screen_id: screenId,
          body: commentBody.trim(),
          guest_name: guestName.trim() || undefined,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Não foi possível enviar o comentário');
      }
      const created = await res.json();
      setComments(prev => [...prev, created]);
      setCommentBody('');
    } catch (err: any) {
      setCommentError(err.message);
    } finally {
      setSendingComment(false);
    }
  };

  // Gera HTML e Mock Runtime isolado declarativamente para renderizar via srcDoc
  const htmlDoc = useMemo(() => {
    if (!activeScreen) return '';
    const cssVars = Object.entries(tokens)
      .map(([k, v]) => `--${k}: ${v};`)
      .join('\n');

    return `
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <script src="https://cdn.tailwindcss.com"></script>
          <style>
            :root {
              ${cssVars}
            }
            body {
              margin: 0;
              padding: 0;
              min-height: 100vh;
              background-color: var(--color-bg, #0b1120);
              color: var(--color-text, #f8fafc);
              font-family: var(--font-body, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
            }
          </style>
        </head>
        <body>
          <div id="mockbird-root" style="width: 100%; min-height: 100vh;">
            ${activeScreen.html_content}
          </div>
          <script>
            // Runtime interativo do CEO
            document.addEventListener('click', (e) => {
              const toastEl = e.target.closest('[data-toast]');
              if (toastEl) {
                const msg = toastEl.getAttribute('data-toast');
                window.parent.postMessage({ type: 'MOCK_TOAST', message: msg }, '*');
              }
            });
          </script>
        </body>
      </html>
    `;
  }, [activeScreen, tokens]);

  if (needsPassword) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex items-center justify-center p-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            loadPresentation(password);
          }}
          className="w-full max-w-sm bg-mockbird-surface border border-mockbird-border rounded-2xl p-6 space-y-4"
        >
          <div className="flex items-center gap-2 text-white font-semibold">
            <Lock size={16} className="text-mockbird-cyan" /> Apresentação protegida
          </div>
          <p className="text-xs text-slate-400">Informe a senha recebida para abrir este protótipo.</p>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Senha de acesso"
            className="w-full px-3 py-2 rounded-lg bg-mockbird-bg border border-mockbird-border text-sm text-white focus:outline-none focus:border-mockbird-cyan"
          />
          {passwordError && <p className="text-xs text-rose-400">{passwordError}</p>}
          <button type="submit" className="w-full bg-mockbird-blue hover:bg-mockbird-bluedark text-white text-xs font-semibold py-2 rounded-lg">
            Abrir apresentação
          </button>
        </form>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <div className="w-4 h-4 border-2 border-mockbird-blue border-t-transparent rounded-full animate-spin"></div>
          <span>Carregando protótipo para apresentação...</span>
        </div>
      </div>
    );
  }

  if (error || !projectData) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex flex-col items-center justify-center p-6 text-center">
        <h1 className="text-xl font-bold text-white mb-2">Protótipo não encontrado</h1>
        <p className="text-sm text-slate-400 max-w-md mb-6">{error || 'O link pode estar expirado ou o slug foi alterado.'}</p>
        {onBackToApp && (
          <button
            onClick={onBackToApp}
            className="bg-mockbird-blue text-white text-xs font-semibold px-4 py-2 rounded-lg"
          >
            Voltar ao Painel
          </button>
        )}
      </div>
    );
  }

  const screens = projectData.screens || [];

  return (
    <div className="min-h-screen w-screen bg-[#09090b] flex flex-col overflow-hidden select-none">
      
      {/* Toast flutuante de interação */}
      {toastMessage && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 bg-mockbird-blue hover:bg-mockbird-bluedark text-white px-5 py-2.5 rounded-xl shadow-panel flex items-center gap-2.5 text-xs font-semibold animate-in slide-in-from-top-4">
          <Bell size={15} className="text-mockbird-cyan animate-pulse" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Barra de Controle Discreta do CEO */}
      <div className="h-12 bg-mockbird-surface/95 border-b border-mockbird-border px-5 flex items-center justify-between gap-4 z-40 backdrop-blur-md shrink-0">
        <div className="flex items-center gap-4">
          {onBackToApp && (
            <button
              onClick={onBackToApp}
              className="text-slate-400 hover:text-white flex items-center gap-1.5 text-xs font-medium"
              title="Voltar ao Editor"
            >
              <ArrowLeft size={14} />
              <span>Voltar ao App</span>
            </button>
          )}

          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded bg-mockbird-blue hover:bg-mockbird-bluedark flex items-center justify-center text-white text-[10px] font-semibold">
              M
            </div>
            <span className="font-bold text-xs text-white tracking-tight">
              {projectData.project_name || projectData.name}
            </span>
            <span className="text-[10px] bg-sky-500/10 text-mockbird-cyan border border-sky-500/20 px-2 py-0.5 rounded-full font-bold uppercase">
              Modo Apresentação
            </span>
          </div>
        </div>

        {/* Alternador de Telas da Apresentação */}
        {screens.length > 1 && (
          <div className="flex items-center gap-1 bg-mockbird-card border border-mockbird-border p-1 rounded-lg">
            {screens.map((s: any, idx: number) => (
              <button
                key={s.id || idx}
                onClick={() => setCurrentScreenIndex(idx)}
                className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                  idx === currentScreenIndex
                    ? 'bg-mockbird-blue text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center gap-3">
          {commentsEnabled && (
            <button
              onClick={() => setCommentsOpen(v => !v)}
              className="text-xs font-medium text-slate-300 hover:text-white flex items-center gap-1.5"
              title="Comentários nesta tela"
            >
              <MessageSquare size={14} />
              <span>{comments.length > 0 ? `Comentários (${comments.length})` : 'Comentar'}</span>
            </button>
          )}
          <div className="text-[11px] text-slate-400 font-mono hidden sm:block">
            {activeScreen?.name || 'Tela 1'}
          </div>
        </div>
      </div>

      {/* Frame Fullscreen de Apresentação com Sandbox Estrito (sem allow-same-origin) */}
      <div className="flex-1 w-full h-full bg-[#09090b] overflow-hidden">
        <iframe
          ref={iframeRef}
          title={activeScreen?.name || 'Apresentação'}
          srcDoc={htmlDoc}
          sandbox="allow-scripts allow-forms allow-modals"
          className="w-full h-full border-0"
        />
      </div>

      {commentsEnabled && commentsOpen && (
        <aside className="fixed top-12 right-0 bottom-0 w-80 bg-mockbird-surface border-l border-mockbird-border flex flex-col z-40 shadow-2xl">
          <div className="h-11 px-4 flex items-center justify-between border-b border-mockbird-border shrink-0">
            <span className="text-xs font-semibold text-white flex items-center gap-1.5">
              <MessageSquare size={14} className="text-mockbird-cyan" /> Comentários da tela
            </span>
            <button onClick={() => setCommentsOpen(false)} className="text-slate-400 hover:text-white" aria-label="Fechar comentários">
              <X size={15} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
            {comments.length === 0 && (
              <p className="text-[11px] text-slate-500 text-center py-8">Seja o primeiro a comentar esta tela.</p>
            )}
            {comments.map(c => (
              <div key={c.id} className="p-2.5 rounded-lg bg-mockbird-card border border-mockbird-border text-xs space-y-1">
                <div className="flex items-center justify-between text-[10px] text-slate-400">
                  <span className="font-semibold text-slate-200">{c.author_name}</span>
                  <span className="font-mono">{new Date(c.created_at).toLocaleDateString('pt-BR')}</span>
                </div>
                <p className="text-slate-300 leading-relaxed">{c.body}</p>
              </div>
            ))}
          </div>

          <form onSubmit={submitGuestComment} className="p-3 border-t border-mockbird-border space-y-2 shrink-0">
            <input
              type="text"
              value={guestName}
              onChange={(e) => setGuestName(e.target.value)}
              placeholder="Seu nome (opcional)"
              maxLength={80}
              className="w-full px-2.5 py-1.5 rounded-md bg-mockbird-bg border border-mockbird-border text-xs text-white focus:outline-none focus:border-mockbird-cyan"
            />
            <textarea
              rows={3}
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="Deixe um comentário sobre esta tela…"
              maxLength={4000}
              className="w-full px-2.5 py-1.5 rounded-md bg-mockbird-bg border border-mockbird-border text-xs text-white focus:outline-none focus:border-mockbird-cyan resize-none"
            />
            {commentError && <p className="text-[11px] text-rose-400">{commentError}</p>}
            <button
              type="submit"
              disabled={sendingComment || !commentBody.trim()}
              className="w-full bg-mockbird-blue hover:bg-mockbird-bluedark disabled:opacity-50 text-white text-xs font-semibold py-2 rounded-md flex items-center justify-center gap-1.5"
            >
              <Send size={12} /> {sendingComment ? 'Enviando…' : 'Enviar comentário'}
            </button>
          </form>
        </aside>
      )}
    </div>
  );
};
