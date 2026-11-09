import { useEffect, useRef, useState } from 'react';
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
      if (ev.data?.type === 'MOCK_TOAST') {
        setToastMessage(ev.data.message);
        setTimeout(() => setToastMessage(null), 3000);
      }
    };
    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, []);

  // Injeta HTML e o Mock Runtime leve no iframe
  useEffect(() => {
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
            document.addEventListener('click', (e) => {
              // Verbo: data-toast="Mensagem"
              const toastEl = e.target.closest('[data-toast]');
              if (toastEl) {
                const msg = toastEl.getAttribute('data-toast');
                window.parent.postMessage({ type: 'MOCK_TOAST', message: msg }, '*');
              }

              // Verbo: data-close fecha overlay mais próximo
              const closeEl = e.target.closest('[data-close]');
              if (closeEl) {
                const overlay = closeEl.closest('[data-mb-id*="modal"], [data-mb-id*="overlay"]');
                if (overlay) overlay.style.display = 'none';
              }
            });
          </script>
        </body>
      </html>
    `;

    doc.open();
    doc.write(htmlDoc);
    doc.close();
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
              if (iframeRef.current) iframeRef.current.src = iframeRef.current.src;
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

      {/* Iframe 100% da Janela com Sandbox Seguro */}
      <iframe 
        ref={iframeRef}
        title="Modo Apresentação"
        sandbox="allow-scripts allow-forms allow-modals allow-same-origin"
        className="w-full h-full border-0"
      />
    </div>
  );
}

