import { useEffect, useRef, useState, useMemo } from 'react';
import { RotateCcw, X, Bell } from 'lucide-react';

interface PresentationPlayerProps {
  initialHtml: string;
  tokens: Record<string, string>;
  projectName?: string;
  onExit: () => void;
}

export function PresentationPlayer({
  initialHtml,
  tokens,
  projectName = 'Apresentação Mockbird',
  onExit
}: PresentationPlayerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Escuta mensagens vindas do runtime do protótipo dentro do iframe
  useEffect(() => {
    const handleMsg = (ev: MessageEvent) => {
      if (ev.data?.type === 'MOCK_TOAST' && typeof ev.data.message === 'string') {
        setToastMessage(ev.data.message);
        setTimeout(() => setToastMessage(null), 3000);
      }
    };
    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, []);

  // Gera HTML e Mock Runtime isolado de forma declarativa para renderizar via srcDoc
  const htmlDoc = useMemo(() => {
    const cssVars = Object.entries(tokens)
      .map(([k, v]) => `--${k}: ${v};`)
      .join('\n');

    return `
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8" />
          <script src="https://cdn.tailwindcss.com"></script>
          <style>
            :root { ${cssVars} }
            body {
              margin: 0;
              padding: 0;
              min-height: 100vh;
              background-color: var(--color-bg, #0b1220);
              color: var(--color-text, #e2e8f0);
              font-family: var(--font-body, system-ui, sans-serif);
            }
          </style>
        </head>
        <body>
          <div id="root" style="width: 100%; min-height: 100vh;">
            ${initialHtml}
          </div>
          <script>
            // Runtime de Interação para Apresentação ao CEO
            function post(payload) {
              window.parent.postMessage(payload, '*');
            }

            function mockTarget(node) {
              if (!node || !node.closest) return null;
              const goEl = node.closest('[data-go]');
              if (goEl) {
                const value = (goEl.getAttribute('data-go') || '').trim();
                if (value && value !== '#') return { kind: 'screen', target: value };
              }
              const link = node.closest('a[href]');
              if (!link || link.hasAttribute('download')) return null;
              const href = (link.getAttribute('href') || '').trim();
              if (!href || href === '#' || href.indexOf('javascript:') === 0) return null;
              if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.indexOf('//') === 0) {
                return { kind: 'external', target: href };
              }
              return { kind: 'screen', target: href };
            }

            document.addEventListener('click', (e) => {
              // Verbo: data-toast="Mensagem"
              const toastEl = e.target.closest('[data-toast]');
              if (toastEl) {
                const msg = toastEl.getAttribute('data-toast');
                if (msg) post({ type: 'MOCK_TOAST', message: msg });
              }

              // Verbo: data-overlay abre overlay
              const overlayBtn = e.target.closest('[data-overlay]');
              if (overlayBtn) {
                const id = overlayBtn.getAttribute('data-overlay');
                if (id) {
                  const targetModal = document.getElementById(id) ||
                    document.querySelector('[data-mb-id="' + id + '"]') ||
                    document.querySelector('[data-mb-id*="' + id + '"]');
                  if (targetModal) {
                    e.preventDefault();
                    targetModal.style.display = 'flex';
                    targetModal.classList.remove('hidden');
                    return;
                  }
                }
              }

              // Verbo: data-close fecha overlay mais próximo
              const closeEl = e.target.closest('[data-close]');
              if (closeEl) {
                const overlay = closeEl.closest('[data-mb-id*="modal"], [data-mb-id*="overlay"], [role="dialog"], .fixed');
                if (overlay) {
                  e.preventDefault();
                  overlay.style.display = 'none';
                  return;
                }
              }

              // Navegação entre telas
              const nav = mockTarget(e.target);
              if (nav) {
                e.preventDefault();
                if (nav.kind === 'screen') {
                  post({ type: 'MOCKBIRD_NAVIGATE', target: nav.target });
                } else if (nav.target) {
                  window.open(nav.target, '_blank');
                }
              }
            });

            document.addEventListener('submit', (e) => {
              e.preventDefault();
              const form = e.target;
              if (!form || !form.getAttribute) return;
              const go = (form.getAttribute('data-go') || form.getAttribute('action') || '').trim();
              if (go && go !== '#' && go.indexOf('javascript:') !== 0) {
                post({ type: 'MOCKBIRD_NAVIGATE', target: go });
              }
            });
          </script>
        </body>
      </html>
    `;
  }, [initialHtml, tokens]);

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 flex flex-col w-screen h-screen select-none overflow-hidden">
      {/* Toast Flutuante */}
      {toastMessage && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 bg-teal-600 text-white px-5 py-2.5 rounded-xl shadow-panel flex items-center gap-2 text-xs font-semibold animate-bounce">
          <Bell className="h-4 w-4" />
          {toastMessage}
        </div>
      )}

      {/* Barra Minimalista de Apresentação (Hover no Topo) */}
      <div className="absolute top-0 inset-x-0 h-12 flex items-center justify-between px-6 z-40 bg-gradient-to-b from-slate-950/80 to-transparent opacity-0 hover:opacity-100 transition duration-200">
        <span className="text-xs font-semibold text-slate-300 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-400"></span>
          {projectName} · Modo Apresentação CEO
        </span>

        <div className="flex items-center gap-2">
          <button 
            onClick={() => {
              // Reinicia o iframe recarregando
              if (iframeRef.current) iframeRef.current.srcdoc = htmlDoc;
            }}
            className="p-1.5 rounded-lg bg-slate-900/90 border border-slate-700 text-slate-300 hover:text-white transition"
            title="Reiniciar Fluxo"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
          <button 
            onClick={onExit}
            className="px-3 py-1 rounded-lg bg-slate-900/90 border border-slate-700 text-slate-300 hover:text-white text-xs font-medium flex items-center gap-1.5 transition"
          >
            <X className="h-3.5 w-3.5" /> Sair (Esc)
          </button>
        </div>
      </div>

      {/* Iframe 100% da Janela com Sandbox Estrito (sem allow-same-origin para isolamento total) */}
      <iframe 
        ref={iframeRef}
        title="Modo Apresentação"
        srcDoc={htmlDoc}
        sandbox="allow-scripts allow-forms allow-modals"
        className="w-full h-full border-0"
      />
    </div>
  );
}

