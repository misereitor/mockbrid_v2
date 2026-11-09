import React, {
  useState,
  useRef,
  useEffect,
  useMemo,
  useImperativeHandle,
  forwardRef,
  useCallback,
} from 'react';
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  Copy,
  Trash2,
  ArrowUp,
  ArrowDown,
  Sliders,
  Code2,
  Sparkles,
  MessageSquarePlus,
  Layers,
  MousePointer,
  Hand,
  MousePointerClick,
} from 'lucide-react';

export interface SelectedElementInfo {
  mbId: string;
  tag: string;
  text?: string;
  selector?: string;
  snippet?: string;
  styles: {
    text?: string;
    bg?: string;
    color?: string;
    borderRadius?: string;
    padding?: string;
    fontSize?: string;
  };
}

export interface CanvasEditorHandle {
  applyStylePatch: (patch: any) => void;
  sendAction: (actionType: string) => void;
  fitToScreen: () => void;
  setZoom: (zoom: number) => void;
  captureScreenshot: () => Promise<string>;
  patchElement?: (html: string, target?: { mbId?: string; selector?: string }) => void;
}

interface CanvasEditorProps {
  initialHtml: string;
  tokens: Record<string, string>;
  onHtmlChange: (newHtml: string) => void;
  width?: number;
  height?: number;
  onElementSelected?: (el: SelectedElementInfo | null) => void;
  onRequestOpenTab?: (tab: 'visual' | 'code' | 'comments' | 'ai' | 'blocks') => void;
  onNewCommentOnElement?: (selector: string, snippet?: string) => void;
}

interface ContextMenuState {
  open: boolean;
  x: number;
  y: number;
  kind: 'canvas' | 'element';
  target?: {
    mbId: string;
    tag: string;
    selector: string;
    snippet: string;
  };
}

const ZOOM_MIN = 0.2;
const ZOOM_MAX = 3.0;

export const CanvasEditor = forwardRef<CanvasEditorHandle, CanvasEditorProps>(({
  initialHtml,
  tokens,
  onHtmlChange,
  width = 1440,
  height = 900,
  onElementSelected,
  onRequestOpenTab,
  onNewCommentOnElement,
}, ref) => {
  const [scale, setScale] = useState(0.75);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [selectedMbId, setSelectedMbId] = useState<string | null>(null);
  const [selectedTag, setSelectedTag] = useState<string>('');
  const [copiedNotification, setCopiedNotification] = useState<string | null>(null);

  const [canvasMode, setCanvasMode] = useState<'edit' | 'interactive'>('edit');
  const [docVersion, setDocVersion] = useState(0);

  const [ctxMenu, setCtxMenu] = useState<ContextMenuState>({
    open: false,
    x: 0,
    y: 0,
    kind: 'canvas',
  });

  const startPanRef = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const prevInitialHtmlRef = useRef(initialHtml);

  // Sincroniza quando initialHtml muda de fora (ex: IA aplicou código novo)
  useEffect(() => {
    if (initialHtml !== prevInitialHtmlRef.current) {
      prevInitialHtmlRef.current = initialHtml;
      setDocVersion((v) => v + 1);
    }
  }, [initialHtml]);

  // Fecha o menu de contexto
  const closeContextMenu = useCallback(() => {
    setCtxMenu((prev) => (prev.open ? { ...prev, open: false } : prev));
  }, []);

  // Notifica o iframe sempre que o modo do canvas mudar (editar vs interagir)
  useEffect(() => {
    iframeRef.current?.contentWindow?.postMessage({
      type: 'MOCKBIRD_SET_MODE',
      mode: canvasMode,
    }, '*');
  }, [canvasMode, docVersion]);

  // Fit: ajusta o frame à área disponível centralizado
  const fitToScreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const availW = el.clientWidth - 80;
    const availH = el.clientHeight - 100;
    const next = Math.min(1.2, Math.max(ZOOM_MIN, Math.min(availW / width, availH / (height + 36))));
    setScale(Math.floor(next * 100) / 100);
    setPan({ x: 0, y: 0 });
  }, [width, height]);

  // Zoom centralizado ou em coordenadas específicas
  const zoomAtPoint = useCallback((factor: number, clientX?: number, clientY?: number) => {
    setScale((prevScale) => {
      const nextScale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, prevScale * factor));
      if (nextScale === prevScale) return prevScale;

      const container = containerRef.current;
      if (container && clientX !== undefined && clientY !== undefined) {
        const rect = container.getBoundingClientRect();
        const mouseX = clientX - rect.left - rect.width / 2;
        const mouseY = clientY - rect.top - rect.height / 2;

        setPan((prevPan) => {
          const ratio = nextScale / prevScale;
          return {
            x: Math.round(mouseX - (mouseX - prevPan.x) * ratio),
            y: Math.round(mouseY - (mouseY - prevPan.y) * ratio),
          };
        });
      }

      return Math.round(nextScale * 100) / 100;
    });
  }, []);

  // Expor métodos via ref imperativo
  useImperativeHandle(ref, () => ({
    applyStylePatch: (patch: any) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_UPDATE_ELEMENT',
        patch,
      }, '*');
    },
    patchElement: (html: string, target?: { mbId?: string; selector?: string }) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_PATCH_ELEMENT',
        html,
        mbId: target?.mbId,
        selector: target?.selector
      }, '*');
    },
    sendAction: (actionType: string) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: actionType,
      }, '*');
    },
    fitToScreen,
    setZoom: (z: number) => {
      setScale(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z)));
    },
    captureScreenshot: async (): Promise<string> => {
      return '';
    },
  }), [fitToScreen]);

  // Ajuste automático inicial
  useEffect(() => {
    fitToScreen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  // Script injetado no iframe: lida com cliques, seleção, postMessages e MENU DE CONTEXTO
  const builtHtmlDoc = useMemo(() => {
    const cssVars = Object.entries(tokens)
      .map(([k, v]) => `--${k}: ${v};`)
      .join('\n');

    const injectionScript = `
      <script>
        let selectedEl = null;
        let currentMode = '${canvasMode}';

        function emitHtmlChanged() {
          const root = document.getElementById('mockbird-root') || document.body;
          const clone = root.cloneNode(true);
          const sel = clone.querySelector('.mb-selected');
          if (sel) sel.classList.remove('mb-selected');
          window.parent.postMessage({
            type: 'MOCKBIRD_HTML_CHANGED',
            html: clone.innerHTML
          }, '*');
        }

        function extractSnippet(target) {
          if (!target) return '';
          const text = (target.innerText || '').trim().replace(/\\s+/g, ' ');
          if (text) return text.length > 36 ? text.substring(0, 36) + '…' : text;
          const img = target.querySelector('img') || (target.tagName.toLowerCase() === 'img' ? target : null);
          if (img && img.src) {
            const parts = img.src.split('/');
            return parts[parts.length - 1].substring(0, 30);
          }
          return '';
        }

        function buildSelector(target) {
          if (!target || target === document.body) return '';
          const tag = target.tagName.toLowerCase();
          const id = target.id ? '#' + target.id : '';
          const classes = Array.from(target.classList || [])
            .filter(c => !c.startsWith('mb-'))
            .slice(0, 2)
            .map(c => '.' + c)
            .join('');
          return tag + id + classes;
        }

        function selectElement(target) {
          if (selectedEl) selectedEl.classList.remove('mb-selected');
          selectedEl = target;
          if (selectedEl) selectedEl.classList.add('mb-selected');

          if (!selectedEl) {
            window.parent.postMessage({ type: 'MOCKBIRD_DESELECT' }, '*');
            return;
          }

          const mbId = target.getAttribute('data-mb-id') || target.tagName.toLowerCase();
          const computed = window.getComputedStyle(target);

          window.parent.postMessage({
            type: 'MOCKBIRD_ELEMENT_SELECTED',
            mbId: mbId,
            tag: target.tagName.toLowerCase(),
            text: target.innerText || '',
            selector: buildSelector(target),
            snippet: extractSnippet(target),
            styles: {
              color: computed.color,
              backgroundColor: computed.backgroundColor,
              padding: computed.padding,
              fontSize: computed.fontSize,
              borderRadius: computed.borderRadius
            }
          }, '*');
        }

        // FECHA O MENU DE CONTEXTO DO PAI IMEDIATAMENTE AO CLICAR NO IFRAME
        document.addEventListener('pointerdown', () => {
          window.parent.postMessage({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' }, '*');
        }, true);

        // Clique simples
        document.addEventListener('click', (e) => {
          window.parent.postMessage({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' }, '*');
          if (currentMode === 'interactive') return; // Modo interativo: deixa a página funcionar livremente!

          const target = e.target.closest('[data-mb-id]') || e.target;
          if (target && target !== document.body && target !== document.documentElement) {
            e.preventDefault();
            e.stopPropagation();
            selectElement(target);
          } else {
            selectElement(null);
          }
        });

        // BOTÃO DIREITO / CONTEXTMENU
        document.addEventListener('contextmenu', (e) => {
          window.parent.postMessage({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' }, '*');

          // MECANISMO PARA O BOTÃO DIREITO DA PÁGINA:
          // Se estiver no Modo Interativo OU se o usuário segurar Shift ou Alt:
          // NÃO intercepta! Permite que a página execute seu próprio menu de contexto nativo!
          if (currentMode === 'interactive' || e.shiftKey || e.altKey) {
            return;
          }

          // Modo edição: abre o menu de contexto do Mockbird
          e.preventDefault();
          e.stopPropagation();
          const target = e.target.closest('[data-mb-id]') || (e.target !== document.body && e.target !== document.documentElement ? e.target : null);
          if (target) {
            selectElement(target);
            window.parent.postMessage({
              type: 'MOCKBIRD_CONTEXT_MENU',
              kind: 'element',
              clientX: e.clientX,
              clientY: e.clientY,
              target: {
                mbId: target.getAttribute('data-mb-id') || target.tagName.toLowerCase(),
                tag: target.tagName.toLowerCase(),
                selector: buildSelector(target),
                snippet: extractSnippet(target),
                outerHtml: target.outerHTML
              }
            }, '*');
          } else {
            selectElement(null);
            window.parent.postMessage({
              type: 'MOCKBIRD_CONTEXT_MENU',
              kind: 'canvas',
              clientX: e.clientX,
              clientY: e.clientY
            }, '*');
          }
        });

        // Fechar menu de contexto no pai ao rolar dentro do iframe
        window.addEventListener('wheel', () => {
          window.parent.postMessage({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' }, '*');
        }, { passive: true });

        // Mensagens do pai
        window.addEventListener('message', (ev) => {
          if (!ev.data) return;

          if (ev.data.type === 'MOCKBIRD_SET_MODE') {
            currentMode = ev.data.mode || 'edit';
            if (currentMode === 'interactive') {
              document.body.classList.add('mb-interactive');
              if (selectedEl) selectedEl.classList.remove('mb-selected');
              selectedEl = null;
            } else {
              document.body.classList.remove('mb-interactive');
            }
            return;
          }

          if (ev.data.type === 'MOCKBIRD_REQUEST_OUTER_HTML') {
            if (selectedEl) {
              window.parent.postMessage({
                type: 'MOCKBIRD_OUTER_HTML_RESPONSE',
                html: selectedEl.outerHTML
              }, '*');
            }
            return;
          }

          if (!selectedEl) return;

          if (ev.data.type === 'MOCKBIRD_UPDATE_ELEMENT') {
            const { text, bg, color, borderRadius, padding } = ev.data.patch || {};
            if (text !== undefined && selectedEl.children.length === 0) selectedEl.innerText = text;
            if (bg) selectedEl.style.backgroundColor = bg;
            if (color) selectedEl.style.color = color;
            if (borderRadius) selectedEl.style.borderRadius = borderRadius;
            if (padding) selectedEl.style.padding = padding;
            emitHtmlChanged();
          } else if (ev.data.type === 'MOCKBIRD_MOVE_UP') {
            const prev = selectedEl.previousElementSibling;
            if (prev) {
              prev.before(selectedEl);
              emitHtmlChanged();
            }
          } else if (ev.data.type === 'MOCKBIRD_MOVE_DOWN') {
            const next = selectedEl.nextElementSibling;
            if (next) {
              next.after(selectedEl);
              emitHtmlChanged();
            }
          } else if (ev.data.type === 'MOCKBIRD_DUPLICATE') {
            const clone = selectedEl.cloneNode(true);
            clone.classList.remove('mb-selected');
            if (clone.hasAttribute('data-mb-id')) {
              clone.setAttribute('data-mb-id', clone.getAttribute('data-mb-id') + '-copy');
            }
            selectedEl.after(clone);
            selectElement(clone);
            emitHtmlChanged();
          } else if (ev.data.type === 'MOCKBIRD_DELETE') {
            const parent = selectedEl.parentElement;
            selectedEl.remove();
            selectedEl = null;
            selectElement(null);
            emitHtmlChanged();
          } else if (ev.data.type === 'MOCKBIRD_PATCH_ELEMENT') {
            const newSnippet = (ev.data.html || '').trim();
            const targetMbId = ev.data.mbId;
            const targetSel = ev.data.selector;
            let target = selectedEl;
            if (!target && targetMbId) {
              target = document.querySelector('[data-mb-id="' + targetMbId + '"]') || document.getElementById(targetMbId);
            }
            if (!target && targetSel) {
              try { target = document.querySelector(targetSel); } catch(e) {}
            }
            if (target && newSnippet) {
              const temp = document.createElement('div');
              temp.innerHTML = newSnippet;
              const newEl = temp.firstElementChild || temp;
              target.replaceWith(newEl);
              selectElement(newEl);
              emitHtmlChanged();
            }
          }
        });
      </script>
      <style>
        :root { ${cssVars} }
        body:not(.mb-interactive) [data-mb-id]:hover, body:not(.mb-interactive) *:hover {
          outline: 1px dashed #5e6ad2 !important;
          outline-offset: 1px;
          cursor: pointer;
        }
        body:not(.mb-interactive) .mb-selected {
          outline: 2px solid #5e6ad2 !important;
          outline-offset: 2px;
          box-shadow: 0 0 0 4px rgba(94, 106, 210, 0.25) !important;
        }
        body.mb-interactive * {
          cursor: auto !important;
        }
      </style>
    `;

    const raw = (initialHtml || '').trim();

    if (raw.toLowerCase().includes('<!doctype') || raw.toLowerCase().includes('<html')) {
      const tailwindScript = '<script src="https://cdn.tailwindcss.com"></script>';
      if (raw.includes('</head>')) {
        return raw.replace('</head>', `${tailwindScript}${injectionScript}</head>`);
      } else if (raw.includes('</body>')) {
        return raw.replace('</body>', `${tailwindScript}${injectionScript}</body>`);
      }
      return `${raw}\n${tailwindScript}${injectionScript}`;
    }

    return `
      <!doctype html>
      <html lang="pt-BR">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <script src="https://cdn.tailwindcss.com"></script>
          ${injectionScript}
          <style>
            body {
              margin: 0;
              padding: 0;
              min-height: 100vh;
              background-color: var(--color-bg, #09090b);
              color: var(--color-text, #f4f4f5);
              font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              user-select: none;
            }
          </style>
        </head>
        <body>
          <div id="mockbird-root" style="width: 100%; min-height: 100vh;">
            ${raw || '<div class="min-h-screen flex items-center justify-center text-slate-500 font-mono text-xs">Tela vazia</div>'}
          </div>
        </body>
      </html>
    `;
  }, [initialHtml, tokens, canvasMode]);

  // Mensagens do iframe
  useEffect(() => {
    const handleMsg = (e: MessageEvent) => {
      if (!e.data) return;

      if (e.data.type === 'MOCKBIRD_ELEMENT_SELECTED') {
        setSelectedMbId(e.data.mbId);
        setSelectedTag(e.data.tag);
        if (onElementSelected) {
          onElementSelected({
            mbId: e.data.mbId,
            tag: e.data.tag,
            selector: e.data.selector,
            snippet: e.data.snippet,
            styles: {
              text: e.data.text,
              ...e.data.styles,
            },
          });
        }
      } else if (e.data.type === 'MOCKBIRD_DESELECT') {
        setSelectedMbId(null);
        setSelectedTag('');
        if (onElementSelected) onElementSelected(null);
      } else if (e.data.type === 'MOCKBIRD_HTML_CHANGED') {
        prevInitialHtmlRef.current = e.data.html;
        onHtmlChange(e.data.html);
      } else if (e.data.type === 'MOCKBIRD_CLOSE_CONTEXT_MENU') {
        closeContextMenu();
      } else if (e.data.type === 'MOCKBIRD_CONTEXT_MENU') {
        // O iframe disparou contextmenu. Converte as coordenadas do iframe para coordenadas da janela
        const iframe = iframeRef.current;
        if (!iframe) return;
        const rect = iframe.getBoundingClientRect();
        const clientX = rect.left + (e.data.clientX || 0) * scale;
        const clientY = rect.top + (e.data.clientY || 0) * scale;

        setCtxMenu({
          open: true,
          x: Math.max(8, Math.min(clientX, window.innerWidth - 260)),
          y: Math.max(8, Math.min(clientY, window.innerHeight - 300)),
          kind: e.data.kind || 'element',
          target: e.data.target,
        });
      }
    };

    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, [onHtmlChange, onElementSelected, scale, closeContextMenu]);

  // Listener nativo de wheel para zoom com Ctrl/Meta e Pan com scroll
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      closeContextMenu();

      if (e.ctrlKey || e.metaKey) {
        const factor = Math.exp(-e.deltaY * 0.003);
        zoomAtPoint(factor, e.clientX, e.clientY);
      } else {
        setPan((prev) => ({
          x: Math.round(prev.x - e.deltaX),
          y: Math.round(prev.y - e.deltaY),
        }));
      }
    };

    el.addEventListener('wheel', handleWheelNative, { passive: false });
    return () => el.removeEventListener('wheel', handleWheelNative);
  }, [zoomAtPoint, closeContextMenu]);

  // Teclado: atalhos de zoom e delete
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || (active as HTMLElement).isContentEditable)) {
        return;
      }

      if (e.key === 'Escape') {
        closeContextMenu();
        return;
      }

      // Ctrl + + (zoom in)
      if ((e.ctrlKey || e.metaKey) && (e.key === '+' || e.key === '=')) {
        e.preventDefault();
        zoomAtPoint(1.2);
        return;
      }

      // Ctrl + - (zoom out)
      if ((e.ctrlKey || e.metaKey) && e.key === '-') {
        e.preventDefault();
        zoomAtPoint(1 / 1.2);
        return;
      }

      // Ctrl + 0 (reset 100%)
      if ((e.ctrlKey || e.metaKey) && e.key === '0') {
        e.preventDefault();
        setScale(1);
        setPan({ x: 0, y: 0 });
        return;
      }

      // Shift + 1 (fit to screen)
      if (e.shiftKey && e.key === '!') {
        e.preventDefault();
        fitToScreen();
        return;
      }

      // Delete / Backspace no elemento selecionado
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedMbId) {
        e.preventDefault();
        iframeRef.current?.contentWindow?.postMessage({ type: 'MOCKBIRD_DELETE' }, '*');
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [zoomAtPoint, fitToScreen, closeContextMenu, selectedMbId]);

  // Fechar menu de contexto ao clicar fora ou redimensionar janela
  useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeContextMenu();
      }
    };
    const onResize = () => closeContextMenu();

    window.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('resize', onResize);
    };
  }, [closeContextMenu]);

  // Contextmenu no container de fora (área cinza do canvas)
  const handleCanvasContextMenu = (e: React.MouseEvent) => {
    // Se o usuário segurar Shift ou Alt, não intercepta (permite botão direito nativo)
    if (e.shiftKey || e.altKey) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({
      open: true,
      x: Math.max(8, Math.min(e.clientX, window.innerWidth - 260)),
      y: Math.max(8, Math.min(e.clientY, window.innerHeight - 300)),
      kind: 'canvas',
    });
  };

  // Pan com arraste
  const handleMouseDown = (e: React.MouseEvent) => {
    closeContextMenu();
    // Botão do meio (1) ou botão esquerdo (0) no fundo
    if (e.button === 1 || (e.button === 0 && e.target === containerRef.current)) {
      e.preventDefault();
      setIsPanning(true);
      startPanRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isPanning) return;
    setPan({
      x: e.clientX - startPanRef.current.x,
      y: e.clientY - startPanRef.current.y,
    });
  };

  const handleMouseUp = () => setIsPanning(false);

  // Ações do menu de contexto
  const notifyCopied = (label: string) => {
    setCopiedNotification(label);
    setTimeout(() => setCopiedNotification(null), 1800);
  };

  const handleCopySelector = () => {
    const sel = ctxMenu.target?.selector || selectedTag;
    if (sel) {
      navigator.clipboard.writeText(sel);
      notifyCopied('Seletor copiado!');
    }
    closeContextMenu();
  };

  const handleCopyHtml = () => {
    const onResponse = (ev: MessageEvent) => {
      if (ev.data?.type === 'MOCKBIRD_OUTER_HTML_RESPONSE') {
        window.removeEventListener('message', onResponse);
        navigator.clipboard.writeText(ev.data.html || '');
        notifyCopied('HTML copiado!');
      }
    };
    window.addEventListener('message', onResponse);
    iframeRef.current?.contentWindow?.postMessage({ type: 'MOCKBIRD_REQUEST_OUTER_HTML' }, '*');
    closeContextMenu();
  };

  const handleComment = () => {
    const sel = ctxMenu.target?.selector || selectedTag || 'elemento';
    const snip = ctxMenu.target?.snippet;
    closeContextMenu();
    if (onNewCommentOnElement) {
      onNewCommentOnElement(sel, snip);
    } else if (onRequestOpenTab) {
      onRequestOpenTab('comments');
    }
  };

  const handleInspect = () => {
    closeContextMenu();
    if (onRequestOpenTab) onRequestOpenTab('visual');
  };

  const handleAction = (type: string) => {
    closeContextMenu();
    iframeRef.current?.contentWindow?.postMessage({ type }, '*');
  };

  return (
    <div className="flex-1 flex h-full overflow-hidden relative select-none">
      {/* Toast de notificação rápida de cópia */}
      {copiedNotification && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-50 px-3 py-1.5 rounded-md bg-mockbird-surface border border-mockbird-border text-xs text-slate-100 shadow-panel animate-in fade-in slide-in-from-top-2">
          {copiedNotification}
        </div>
      )}

      {/* Área Infinita do Canvas */}
      <div
        ref={containerRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onContextMenu={handleCanvasContextMenu}
        className={`flex-1 bg-mockbird-bg flex items-center justify-center overflow-hidden relative cursor-default ${
          isPanning ? 'cursor-grab active:cursor-grabbing' : ''
        }`}
        style={{
          backgroundImage: 'radial-gradient(circle, #27272a 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      >
        {/* Barra de Controles de Zoom Flutuante (Canto Inferior Esquerdo) */}
        <div className="absolute bottom-5 left-5 z-20 flex items-center gap-1 p-1 rounded-lg bg-mockbird-surface/95 border border-mockbird-border shadow-panel backdrop-blur-md">
          <button
            type="button"
            onClick={() => zoomAtPoint(1 / 1.2)}
            className="mb-btn-ghost !p-1.5"
            title="Reduzir zoom (Ctrl -)"
            aria-label="Reduzir zoom"
          >
            <ZoomOut size={14} />
          </button>

          <button
            type="button"
            onClick={() => {
              setScale(1);
              setPan({ x: 0, y: 0 });
            }}
            className="px-2 py-1 text-xs font-mono font-medium text-slate-300 hover:text-white rounded hover:bg-mockbird-card min-w-[50px] text-center"
            title="Resetar para 100% (Ctrl 0)"
          >
            {Math.round(scale * 100)}%
          </button>

          <button
            type="button"
            onClick={() => zoomAtPoint(1.2)}
            className="mb-btn-ghost !p-1.5"
            title="Aumentar zoom (Ctrl +)"
            aria-label="Aumentar zoom"
          >
            <ZoomIn size={14} />
          </button>

          <div className="h-4 w-px bg-mockbird-border mx-0.5" />

          <button
            type="button"
            onClick={fitToScreen}
            className="mb-btn-ghost !p-1.5"
            title="Ajustar à tela (Shift !)"
            aria-label="Ajustar à tela"
          >
            <Maximize2 size={14} />
          </button>
        </div>

        {/* Seletor de Modo: Edição vs Interativo (Canto Inferior Direito) */}
        <div className="absolute bottom-5 right-5 z-20 flex items-center p-1 rounded-lg bg-mockbird-surface/95 border border-mockbird-border shadow-panel backdrop-blur-md text-xs">
          <button
            type="button"
            onClick={() => setCanvasMode('edit')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
              canvasMode === 'edit'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Modo Edição: Seleciona blocos, inspeciona e abre menu Mockbird"
          >
            <MousePointer size={13} />
            <span>Editar</span>
          </button>
          <button
            type="button"
            onClick={() => setCanvasMode('interactive')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
              canvasMode === 'interactive'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Modo Interativo: Libera formulários, cliques e botão direito nativo da página"
          >
            <Hand size={13} />
            <span>Interagir</span>
          </button>
        </div>

        {/* Quadro da Tela (Artboard) */}
        <div
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
            transformOrigin: 'center center',
            transition: isPanning ? 'none' : 'transform 80ms ease-out',
          }}
          className="shadow-2xl rounded-xl transition-shadow duration-200"
        >
          {/* Barra Superior do Artboard */}
          <div
            style={{ width: `${width}px` }}
            className="h-9 px-4 rounded-t-xl bg-mockbird-surface border-x border-t border-mockbird-border flex items-center justify-between text-xs text-slate-400 select-none shadow-sm"
          >
            <span className="font-semibold text-slate-200 flex items-center gap-2">
              <span className={`h-1.5 w-1.5 rounded-full ${canvasMode === 'interactive' ? 'bg-emerald-400' : 'bg-mockbird-cyan'}`}></span>
              {canvasMode === 'interactive' ? 'Modo Interativo (Testando página)' : 'Tela Ativa (Edição)'}
            </span>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-slate-500">
                Shift + Botão Dir: menu nativo da página
              </span>
              <span className="font-mono text-[11px] text-slate-500 tabular-nums">
                {width} × {height}
              </span>
            </div>
          </div>

          {/* Iframe com key dinâmica para renderização imediata do patch */}
          <div
            style={{ width: `${width}px`, height: `${height}px` }}
            className="bg-mockbird-surface border-x border-b border-mockbird-border rounded-b-xl overflow-hidden"
          >
            <iframe
              key={`canvas_iframe_${docVersion}`}
              ref={iframeRef}
              srcDoc={builtHtmlDoc}
              title="Mockbird Canvas"
              className="w-full h-full border-0 bg-[#09090b]"
            />
          </div>
        </div>
      </div>

      {/* MENU DE CONTEXTO PERSONALIZADO COM BACKDROP INVISÍVEL GLOBAL */}
      {ctxMenu.open && (
        <>
          {/* Backdrop invisível global que cobre 100% da tela: intercepta qualquer clique fora e fecha na hora */}
          <div
            className="fixed inset-0 z-40 bg-transparent cursor-default pointer-events-auto"
            onPointerDown={(e) => {
              e.preventDefault();
              e.stopPropagation();
              closeContextMenu();
            }}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              closeContextMenu();
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              closeContextMenu();
            }}
          />

          <div
            ref={menuRef}
            role="menu"
            aria-label="Menu de contexto"
            style={{ left: `${ctxMenu.x}px`, top: `${ctxMenu.y}px` }}
            className="fixed z-50 min-w-[230px] max-w-[320px] p-1.5 rounded-xl bg-mockbird-surface border border-mockbird-border shadow-2xl text-xs text-slate-200 flex flex-col gap-0.5 animate-in fade-in zoom-in-95 duration-100"
          >
          {ctxMenu.kind === 'element' && ctxMenu.target ? (
            <>
              {/* Cabeçalho do alvo com seletor e snippet */}
              <div className="px-2.5 py-1.5 border-b border-mockbird-border text-[11px] text-slate-400 font-mono truncate mb-1">
                <span className="text-mockbird-cyan font-semibold">&lt;{ctxMenu.target.tag}&gt;</span>
                {ctxMenu.target.selector && (
                  <span className="ml-1 text-slate-400 truncate">{ctxMenu.target.selector}</span>
                )}
                {ctxMenu.target.snippet && (
                  <div className="text-[10px] text-slate-500 truncate font-sans mt-0.5">
                    “{ctxMenu.target.snippet}”
                  </div>
                )}
              </div>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  closeContextMenu();
                  if (onRequestOpenTab) onRequestOpenTab('ai');
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-blue/20 text-mockbird-cyan text-left transition-colors font-semibold"
              >
                <Sparkles size={14} className="text-mockbird-cyan" />
                <span>Pedir alteração à IA</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={handleComment}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <MessageSquarePlus size={14} className="text-mockbird-cyan" />
                <span>Comentar elemento</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={handleInspect}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Sliders size={14} />
                <span>Inspecionar estilos</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={handleCopySelector}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Copy size={14} />
                <span>Copiar seletor CSS</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={handleCopyHtml}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Code2 size={14} />
                <span>Copiar HTML</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={() => handleAction('MOCKBIRD_MOVE_UP')}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <ArrowUp size={14} />
                <span>Mover para cima</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => handleAction('MOCKBIRD_MOVE_DOWN')}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <ArrowDown size={14} />
                <span>Mover para baixo</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => handleAction('MOCKBIRD_DUPLICATE')}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Copy size={14} />
                <span>Duplicar elemento</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={() => handleAction('MOCKBIRD_DELETE')}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-rose-500/10 text-rose-400 text-left transition-colors"
              >
                <Trash2 size={14} />
                <span>Excluir elemento</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setCanvasMode('interactive');
                  closeContextMenu();
                  iframeRef.current?.contentWindow?.postMessage({ type: 'MOCKBIRD_SET_MODE', mode: 'interactive' }, '*');
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors text-slate-300"
              >
                <MousePointerClick size={14} className="text-amber-400" />
                <span>Modo Interativo (Testar página)</span>
              </button>

              <div className="px-2.5 py-1 text-[10px] text-slate-500 flex items-center justify-between">
                <span>Botão direito da página</span>
                <kbd className="px-1 py-0.5 rounded bg-mockbird-card border border-mockbird-border font-mono text-[9px] text-slate-400">Shift + Dir.</kbd>
              </div>
            </>
          ) : (
            <>
              {/* Menu de Canvas (clique no fundo) */}
              <div className="px-2.5 py-1 text-[10px] uppercase font-semibold text-slate-500 tracking-wider">
                Canvas
              </div>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  fitToScreen();
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Maximize2 size={14} />
                <span>Ajustar à tela (Fit)</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setScale(1);
                  setPan({ x: 0, y: 0 });
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <span className="font-mono text-xs w-3.5 text-center">1</span>
                <span>Zoom 100%</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  closeContextMenu();
                  if (onRequestOpenTab) onRequestOpenTab('blocks');
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Layers size={14} />
                <span>Inserir bloco da biblioteca</span>
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  closeContextMenu();
                  if (onRequestOpenTab) onRequestOpenTab('ai');
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors"
              >
                <Sparkles size={14} className="text-mockbird-cyan" />
                <span>Pedir alteração à IA</span>
              </button>

              <div className="h-px bg-mockbird-border my-1" />

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setCanvasMode(canvasMode === 'edit' ? 'interactive' : 'edit');
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-mockbird-card text-left transition-colors text-slate-300"
              >
                <MousePointerClick size={14} className="text-amber-400" />
                <span>{canvasMode === 'edit' ? 'Alternar para Modo Interativo' : 'Alternar para Modo Edição'}</span>
              </button>

              <div className="px-2.5 py-1 text-[10px] text-slate-500 flex items-center justify-between">
                <span>Menu nativo da página</span>
                <kbd className="px-1 py-0.5 rounded bg-mockbird-card border border-mockbird-border font-mono text-[9px] text-slate-400">Shift + Dir.</kbd>
              </div>
            </>
          )}
        </div>
      </>
    )}
    </div>
  );
});
