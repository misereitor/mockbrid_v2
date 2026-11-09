import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Bell } from 'lucide-react';

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
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    fetch(`/api/public/p/${slug}`)
      .then(r => {
        if (!r.ok) throw new Error('Projeto de apresentação não encontrado');
        return r.json();
      })
      .then(d => {
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

  // Listener para eventos interativos no iframe
  useEffect(() => {
    const handleMsg = (ev: MessageEvent) => {
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

  useEffect(() => {
    if (!activeScreen) return;
    const iframe = iframeRef.current;
    if (!iframe) return;
    const doc = iframe.contentDocument || iframe.contentWindow?.document;
    if (!doc) return;

    const cssVars = Object.entries(tokens)
      .map(([k, v]) => `--${k}: ${v};`)
      .join('\n');

    const htmlDoc = `
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

    doc.open();
    doc.write(htmlDoc);
    doc.close();
  }, [activeScreen, tokens]);

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
            <span className="font-bold text-xs text-white tracking-tight">{projectData.name}</span>
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

        <div className="text-[11px] text-slate-400 font-mono hidden sm:block">
          {activeScreen?.name || 'Tela 1'}
        </div>
      </div>

      {/* Frame Fullscreen de Apresentação */}
      <div className="flex-1 w-full h-full bg-[#09090b] overflow-hidden">
        <iframe
          ref={iframeRef}
          title={activeScreen?.name || 'Apresentação'}
          className="w-full h-full border-0"
        />
      </div>
    </div>
  );
};
