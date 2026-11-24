import React, {
  useState,
  useRef,
  useEffect,
  useMemo,
  useImperativeHandle,
  forwardRef,
  useCallback,
} from 'react';
import { buildCanvasDoc } from './lib/canvasDoc';
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
  X,
} from 'lucide-react';
import { CanvasChromeBar } from './components/CanvasChromeBar';

export interface BreadcrumbItem {
  mbId: string;
  tag: string;
  selector?: string;
}

export interface SelectedElementInfo {
  mbId: string;
  tag: string;
  text?: string;
  selector?: string;
  snippet?: string;
  leaf?: boolean;
  breadcrumbs?: BreadcrumbItem[];
  dataGo?: string;
  dataToast?: string;
  dataOverlay?: string;
  dataClose?: string;
  dataMock?: string;
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
  updateAttributes?: (attributes: Record<string, string | null>) => void;
  selectByMbId?: (mbId: string) => void;
  toggleElementVisibility?: (mbId: string) => void;
  sendAction: (actionType: string) => void;
  fitToScreen: () => void;
  setZoom: (zoom: number) => void;
  captureScreenshot: () => Promise<string>;
  patchElement?: (html: string, target?: { mbId?: string; selector?: string }) => void;
  applyScenario?: (data: Record<string, any>) => void;
}

interface CanvasEditorProps {
  initialHtml: string;
  tokens: Record<string, string>;
  theme?: 'light' | 'dark';
  onHtmlChange: (newHtml: string) => void;
  width?: number;
  height?: number;
  onElementSelected?: (el: SelectedElementInfo | null) => void;
  onRequestOpenTab?: (tab: 'visual' | 'code' | 'comments' | 'ai' | 'blocks') => void;
  onNewCommentOnElement?: (selector: string, snippet?: string) => void;
  /** Clique em link/`data-go` no modo mock: navegar para outra tela. */
  onNavigate?: (target: string, external?: boolean) => void;
  /** Desfazer/refazer vindos do Ctrl+Z dentro do canvas. */
  onUndo?: () => void;
  onRedo?: () => void;
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
  theme = 'dark',
  onHtmlChange,
  width = 1440,
  height = 900,
  onElementSelected,
  onRequestOpenTab,
  onNewCommentOnElement,
  onNavigate,
  onUndo,
  onRedo,
}, ref) => {
  const [scale, setScale] = useState(0.75);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [selectedMbId, setSelectedMbId] = useState<string | null>(null);
  const [selectedTag, setSelectedTag] = useState<string>('');
  const [selectionCount, setSelectionCount] = useState(0);
  const [breadcrumbs, setBreadcrumbs] = useState<BreadcrumbItem[]>([]);
  const [copiedNotification, setCopiedNotification] = useState<string | null>(null);

  // O canvas abre como mock navegável; "Editar" trava o clique como seleção.
  const [canvasMode, setCanvasMode] = useState<'edit' | 'hand' | 'interactive'>('interactive');
  const [spacePressed, setSpacePressed] = useState(false);
  const [docVersion, setDocVersion] = useState(0);
  const [canvasWidth, setCanvasWidth] = useState(width);
  const [canvasHeight, setCanvasHeight] = useState(height);
  const [navigationEvent, setNavigationEvent] = useState<{ target: string; id: number }>();
  const navigationIdRef = useRef(0);

  useEffect(() => {
    setCanvasWidth(width);
    setCanvasHeight(height);
  }, [width, height]);

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
  // HTML que origina o documento no canvas
  const [docHtml, setDocHtml] = useState(initialHtml);

  // Sincroniza quando initialHtml muda de fora (troca de tela/rota, IA, etc.)
  useEffect(() => {
    if (initialHtml !== prevInitialHtmlRef.current) {
      prevInitialHtmlRef.current = initialHtml;
      setDocHtml(initialHtml);
    }
  }, [initialHtml]);

  // Fecha o menu de contexto
  const closeContextMenu = useCallback(() => {
    setCtxMenu((prev) => (prev.open ? { ...prev, open: false } : prev));
  }, []);

  // Notifica o iframe sempre que o modo mudar ou o documento for recarregado.
  // O runtime aplica o modo sem remontar o iframe, preservando o estado da página.
  const syncMode = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({
      type: 'MOCKBIRD_SET_MODE',
      mode: canvasMode,
    }, '*');
  }, [canvasMode]);

  useEffect(() => {
    syncMode();
  }, [syncMode, docVersion]);

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
    updateAttributes: (attributes: Record<string, string | null>) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_UPDATE_ATTRIBUTES',
        attributes,
      }, '*');
    },
    selectByMbId: (mbId: string) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_SELECT_BY_MB_ID',
        mbId,
      }, '*');
    },
    toggleElementVisibility: (mbId: string) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_TOGGLE_VISIBILITY',
        mbId,
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
    applyScenario: (data: Record<string, any>) => {
      iframeRef.current?.contentWindow?.postMessage({
        type: 'MOCKBIRD_APPLY_SCENARIO',
        data,
      }, '*');
    },
  }), [fitToScreen]);

  // Ajuste automático inicial
  useEffect(() => {
    fitToScreen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  // Script injetado no iframe: monta o documento do canvas com o runtime de seleção/edição embutido
  const initialThemeRef = useRef(theme);
  const initialTokensRef = useRef(tokens);
  const builtHtmlDoc = useMemo(
    () => buildCanvasDoc(docHtml, initialTokensRef.current, initialThemeRef.current),
    [docHtml, docVersion]
  );

  useEffect(() => {
    if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({
        type: 'MOCKBIRD_SET_THEME',
        theme,
        tokens,
      }, '*');
    }
  }, [theme, tokens]);

  // Mensagens do iframe
  useEffect(() => {
    const handleMsg = (e: MessageEvent) => {
      // Só aceita mensagens vindas do próprio canvas.
      if (e.source !== iframeRef.current?.contentWindow) return;
      if (!e.data) return;

      if (e.data.type === 'MOCKBIRD_ELEMENT_SELECTED') {
        setSelectedMbId(e.data.mbId);
        setSelectedTag(e.data.tag);
        setSelectionCount(Math.max(1, Number(e.data.count) || 1));
        setBreadcrumbs(e.data.breadcrumbs || []);
        if (onElementSelected) {
          onElementSelected({
            mbId: e.data.mbId,
            tag: e.data.tag,
            selector: e.data.selector,
            snippet: e.data.snippet,
            leaf: e.data.leaf,
            breadcrumbs: e.data.breadcrumbs,
            dataGo: e.data.dataGo,
            dataToast: e.data.dataToast,
            dataOverlay: e.data.dataOverlay,
            dataClose: e.data.dataClose ? 'true' : '',
            dataMock: e.data.dataMock,
            styles: {
              text: e.data.text,
              ...e.data.styles,
            },
          });
        }
      } else if (e.data.type === 'MOCKBIRD_DESELECT') {
        setSelectedMbId(null);
        setSelectedTag('');
        setSelectionCount(0);
        setBreadcrumbs([]);
        if (onElementSelected) onElementSelected(null);
      } else if (e.data.type === 'MOCKBIRD_UNDO') {
        onUndo?.();
      } else if (e.data.type === 'MOCKBIRD_REDO') {
        onRedo?.();
      } else if (e.data.type === 'MOCKBIRD_HTML_CHANGED') {
        prevInitialHtmlRef.current = e.data.html;
        onHtmlChange(e.data.html);
      } else if (e.data.type === 'MOCKBIRD_NAVIGATE') {
        const target = String(e.data.target || '');
        navigationIdRef.current += 1;
        setNavigationEvent({ target, id: navigationIdRef.current });
        onNavigate?.(target, Boolean(e.data.external));
      } else if (e.data.type === 'MOCKBIRD_CLOSE_CONTEXT_MENU') {
        closeContextMenu();
      } else if (e.data.type === 'MOCKBIRD_SPACE_KEY') {
        setSpacePressed(Boolean(e.data.pressed));
      } else if (e.data.type === 'MOCKBIRD_IFRAME_WHEEL') {
        closeContextMenu();
        const iframe = iframeRef.current;
        if (!iframe) return;
        const rect = iframe.getBoundingClientRect();
        const clientX = rect.left + (e.data.clientX || 0) * scale;
        const clientY = rect.top + (e.data.clientY || 0) * scale;

        if (e.data.ctrlKey || e.data.metaKey) {
          const factor = Math.exp(-e.data.deltaY * 0.003);
          zoomAtPoint(factor, clientX, clientY);
        } else {
          setPan((prev) => ({
            x: Math.round(prev.x - e.data.deltaX),
            y: Math.round(prev.y - e.data.deltaY),
          }));
        }
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
  }, [onHtmlChange, onElementSelected, scale, closeContextMenu, onNavigate, onUndo, onRedo, zoomAtPoint]);

  // Listener para barra de espaço (Modo Mão / Pan rápido)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat) {
        const active = document.activeElement;
        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || (active as HTMLElement).isContentEditable)) return;
        setSpacePressed(true);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        setSpacePressed(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

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

      // H (Hand mode / Mão) e V (Selection / Editar)
      if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
        if (e.key === 'h' || e.key === 'H') {
          setCanvasMode((prev) => (prev === 'hand' ? 'edit' : 'hand'));
          return;
        }
        if (e.key === 'v' || e.key === 'V') {
          setCanvasMode('edit');
          return;
        }
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
    // Botão do meio (1), ou espaço pressionado, ou modo mão, ou botão esquerdo no fundo
    if (
      e.button === 1 ||
      spacePressed ||
      canvasMode === 'hand' ||
      (e.button === 0 && e.target === containerRef.current)
    ) {
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
      if (ev.source !== iframeRef.current?.contentWindow) return;
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
        className={`flex-1 bg-mockbird-bg flex items-center justify-center overflow-hidden relative ${
          isPanning || spacePressed || canvasMode === 'hand'
            ? 'cursor-grab active:cursor-grabbing'
            : 'cursor-default'
        }`}
        style={{
          backgroundImage: 'radial-gradient(circle, #27272a 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      >
        {/* Barra da seleção: ações em grupo, inclusive com vários elementos */}
        {selectionCount > 0 && (
          <div className="absolute top-4 left-4 z-20 flex items-center gap-1 p-1 rounded-lg bg-mockbird-surface/95 border border-mockbird-border shadow-panel backdrop-blur-md text-xs">
            <span className="px-2 py-1 font-medium text-slate-200 whitespace-nowrap">
              {selectionCount === 1 ? '1 elemento' : `${selectionCount} elementos`}
            </span>
            <div className="h-4 w-px bg-mockbird-border" />
            <button
              type="button"
              onClick={() => handleAction('MOCKBIRD_DUPLICATE')}
              className="mb-btn-ghost !p-1.5"
              title="Duplicar seleção"
              aria-label="Duplicar seleção"
            >
              <Copy size={13} />
            </button>
            <button
              type="button"
              onClick={() => handleAction('MOCKBIRD_DELETE')}
              className="mb-btn-ghost !p-1.5 hover:!text-rose-400"
              title="Excluir seleção (Delete)"
              aria-label="Excluir seleção"
            >
              <Trash2 size={13} />
            </button>
            <button
              type="button"
              onClick={() => handleAction('MOCKBIRD_DESELECT_ALL')}
              className="mb-btn-ghost !p-1.5"
              title="Limpar seleção (Esc)"
              aria-label="Limpar seleção"
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* Trilha de Breadcrumbs (Ancestrais do Elemento Selecionado) */}
        {selectedMbId && breadcrumbs.length > 0 && (
          <div className="absolute top-4 left-44 z-20 hidden md:flex items-center gap-1 py-1 px-2.5 rounded-lg bg-mockbird-surface/95 border border-mockbird-border shadow-panel backdrop-blur-md text-xs text-slate-300 max-w-[50vw] overflow-x-auto">
            {breadcrumbs.map((crumb, idx) => {
              const isLast = idx === breadcrumbs.length - 1;
              return (
                <React.Fragment key={crumb.mbId || idx}>
                  {idx > 0 && <span className="text-slate-600 text-[10px]">›</span>}
                  <button
                    type="button"
                    onClick={() => {
                      iframeRef.current?.contentWindow?.postMessage({
                        type: 'MOCKBIRD_SELECT_BY_MB_ID',
                        mbId: crumb.mbId,
                      }, '*');
                    }}
                    className={`px-1.5 py-0.5 rounded text-[11px] font-mono transition-colors ${
                      isLast
                        ? 'bg-mockbird-blue/20 text-mockbird-cyan font-bold border border-mockbird-blue/30'
                        : 'text-slate-400 hover:text-white hover:bg-mockbird-card'
                    }`}
                    title={`Selecionar <${crumb.tag}> (${crumb.mbId})`}
                  >
                    &lt;{crumb.tag}&gt;
                  </button>
                </React.Fragment>
              );
            })}
          </div>
        )}

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

        {/* Seletor de Modo: Edição vs Mão vs Interativo (Canto Inferior Direito) */}
        <div className="absolute bottom-5 right-5 z-20 flex items-center p-1 rounded-lg bg-mockbird-surface/95 border border-mockbird-border shadow-panel backdrop-blur-md text-xs gap-0.5">
          <button
            type="button"
            onClick={() => setCanvasMode('edit')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
              canvasMode === 'edit'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Modo Edição: clique seleciona, Shift/Ctrl+clique acumula, arraste move e as alças redimensionam"
          >
            <MousePointer size={13} />
            <span>Editar</span>
          </button>
          <button
            type="button"
            onClick={() => setCanvasMode('hand')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
              canvasMode === 'hand'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Modo Mão (segure Espaço ou tecla H): clique e arraste em qualquer lugar para mover a tela"
          >
            <Hand size={13} />
            <span>Mão</span>
          </button>
          <button
            type="button"
            onClick={() => setCanvasMode('interactive')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
              canvasMode === 'interactive'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Modo Mock: navegação real, modais e formulários ativos como na página final"
          >
            <MousePointerClick size={13} />
            <span>Interagir</span>
          </button>
        </div>

        {/* Quadro da Tela (Artboard) */}
        <div
          data-testid="canvas-transform"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
            transformOrigin: 'center center',
            transition: 'none',
          }}
          className="shadow-2xl rounded-xl"
        >
          {/* Barra de Navegador (Chrome Bar Completa) */}
          <CanvasChromeBar
            width={canvasWidth}
            height={canvasHeight}
            zoom={scale}
            iframeRef={iframeRef}
            onNavigate={(target, external) => onNavigate?.(target, external)}
            onReload={() => setDocVersion((v) => v + 1)}
            onViewportChange={(nextWidth, nextHeight) => {
              setCanvasWidth(nextWidth);
              setCanvasHeight(nextHeight);
              setPan({ x: 0, y: 0 });
            }}
            onZoom={(nextZoom) => setScale(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, nextZoom)))}
            onFitToScreen={fitToScreen}
            navigationEvent={navigationEvent}
          />

          {/* Iframe com key dinâmica para renderização imediata do patch */}
          <div
            style={{ width: `${canvasWidth}px`, height: `${canvasHeight}px` }}
            className="bg-[#09090b] border-x border-[#3c4043] overflow-hidden relative shadow-inner"
          >
            {/* Overlay transparente ativo durante Pan ou modo Mão para capturar arrasto sem engolir mouse no iframe */}
            {(isPanning || spacePressed || canvasMode === 'hand') && (
              <div
                onMouseDown={handleMouseDown}
                className="absolute inset-0 z-30 cursor-grab active:cursor-grabbing bg-transparent"
              />
            )}
            {/* Sem allow-same-origin: HTML gerado por IA/MCP roda em origem opaca
                e não consegue ler cookies nem chamar a API do app. */}
            <iframe
              key={`canvas_iframe_${docVersion}`}
              ref={iframeRef}
              data-mockbird-canvas="frame"
              srcDoc={builtHtmlDoc}
              title="Mockbird Canvas"
              sandbox="allow-scripts allow-forms allow-modals"
              onLoad={syncMode}
              className="w-full h-full border-0 bg-[#09090b]"
            />
          </div>

          {/* Barra de Status da Janela do Navegador (Rodapé) */}
          <div
            style={{ width: `${canvasWidth}px` }}
            className="h-7 px-3 bg-[#202124] border-x border-b border-[#3c4043] rounded-b-xl flex items-center justify-between text-[11px] text-[#9aa0a6] select-none"
          >
            <span className="font-medium text-slate-300 flex items-center gap-2">
              <span className={`h-1.5 w-1.5 rounded-full ${canvasMode === 'interactive' ? 'bg-emerald-400' : 'bg-[#8ab4f8]'}`}></span>
              {canvasMode === 'interactive'
                ? 'Modo Interativo (Testar página)'
                : canvasMode === 'hand'
                ? 'Modo Mão (Pan)'
                : 'Modo Inspeção & Edição'}
            </span>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-slate-500 hidden sm:inline">
                {canvasMode === 'interactive'
                  ? 'Clique: navegar / interagir · Shift: selecionar'
                  : canvasMode === 'hand'
                  ? 'Arraste para mover o canvas'
                  : 'Clique: selecionar · Duplo-clique: editar texto · F12: DevTools'}
              </span>
              <span className="font-mono text-[11px] text-slate-400 tabular-nums">
                {canvasWidth} × {canvasHeight}
              </span>
            </div>
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
