import React, { useEffect, useState, useMemo, useRef } from 'react';
import { 
  X, 
  Settings, 
  MoreVertical, 
  MousePointer2, 
  Smartphone, 
  Ban, 
  Search, 
  ChevronRight, 
  ChevronDown, 
  PanelRight, 
  PanelBottom,
  AlertTriangle,
  AlertCircle,
  Plus,
  Trash2
} from 'lucide-react';

type NodeItem = {
  id: string;
  tag: string;
  attributes: Record<string, string>;
  textSnippet: string;
  parentId: string | null;
  childIds: string[];
  rect: { width: number; height: number };
};

type ConsoleItem = {
  level: string;
  text: string;
};

type NetworkItem = {
  method: string;
  url: string;
  status: number;
  duration: number;
  ok: boolean;
  error?: string;
};

export interface DevToolsDockProps {
  dockPosition?: 'right' | 'bottom';
  onDockChange?: (position: 'right' | 'bottom') => void;
  onClose?: () => void;
}

const message = (payload: Record<string, unknown>) => {
  document
    .querySelector<HTMLIFrameElement>('iframe[data-mockbird-canvas="frame"]')
    ?.contentWindow?.postMessage(payload, '*');
};

export function DevToolsDock({
  dockPosition = 'right',
  onDockChange,
  onClose,
}: DevToolsDockProps) {
  const [tab, setTab] = useState<'elements' | 'console' | 'network' | 'sources'>('elements');
  const [nodes, setNodes] = useState<NodeItem[]>([]);
  const [consoleItems, setConsoleItems] = useState<ConsoleItem[]>([]);
  const [network, setNetwork] = useState<NetworkItem[]>([]);
  const [inlineStyles, setInlineStyles] = useState<Record<string, string>>({});
  const [computedStyles, setComputedStyles] = useState<Record<string, string>>({});
  const [elementClasses, setElementClasses] = useState<string>('');
  const [selected, setSelected] = useState<string | null>(null);
  const [profile, setProfile] = useState('off');
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [showDockMenu, setShowDockMenu] = useState(false);
  const [consoleInput, setConsoleInput] = useState('');
  const [consoleFilter, setConsoleFilter] = useState('');
  const [inspectActive, setInspectActive] = useState(false);

  // Sub-aba inferior de Elements: Styles ou Computed
  const [elementsSubTab, setElementsSubTab] = useState<'styles' | 'computed'>('styles');
  const [computedFilter, setComputedFilter] = useState('');

  // Estados de Nova Propriedade de Estilo
  const [newPropName, setNewPropName] = useState('');
  const [newPropVal, setNewPropVal] = useState('');
  const [editingClass, setEditingClass] = useState(false);
  const [classInputValue, setClassInputValue] = useState('');

  // 1. Redimensionamento da Janela DevTools
  const [dockWidth, setDockWidth] = useState<number>(() => {
    const saved = localStorage.getItem('mb_devtools_width');
    return saved ? Math.max(320, Math.min(850, Number(saved))) : 480;
  });
  const [dockHeight, setDockHeight] = useState<number>(() => {
    const saved = localStorage.getItem('mb_devtools_height');
    return saved ? Math.max(160, Math.min(600, Number(saved))) : 280;
  });

  // 2. Redimensionamento Interno (Divisão entre Árvore DOM e Styles)
  const [splitPercent, setSplitPercent] = useState<number>(() => {
    const saved = localStorage.getItem('mb_devtools_split_percent');
    return saved ? Math.max(25, Math.min(80, Number(saved))) : 52;
  });

  const isResizingDock = useRef(false);
  const isResizingSplit = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const rootNodes = useMemo(() => nodes.filter((n) => !n.parentId || !nodeMap.has(n.parentId)), [nodes, nodeMap]);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const nodeMapRef = useRef(nodeMap);
  nodeMapRef.current = nodeMap;

  // Função para abrir automaticamente todos os pais até o nó selecionado
  const expandAncestors = (nodeId: string, map: Map<string, NodeItem>) => {
    const toExpand: string[] = [];
    let cur = map.get(nodeId);
    while (cur && cur.parentId) {
      toExpand.push(cur.parentId);
      cur = map.get(cur.parentId);
    }
    if (toExpand.length > 0) {
      setExpandedNodes((prev) => {
        const next = new Set(prev);
        toExpand.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data) return;

      if (data.type === 'MOCKBIRD_DEVTOOLS_CONSOLE') {
        setConsoleItems((items) =>
          [...items, { level: data.level, text: data.text }].slice(-200)
        );
      }
      if (data.type === 'MOCKBIRD_DEVTOOLS_NETWORK') {
        setNetwork((items) => [...items, data].slice(-200));
      }
      if (data.type === 'MOCKBIRD_DEVTOOLS_DOM_TREE') {
        const newNodes = data.nodes || [];
        setNodes(newNodes);

        setExpandedNodes((prev) => {
          if (prev.size === 0 && newNodes.length > 0) {
            const initial = new Set<string>();
            newNodes.forEach((n: NodeItem) => {
              if (n.tag === 'html' || n.tag === 'body') {
                initial.add(n.id);
              }
            });
            return initial;
          }
          return prev;
        });

        if (!selectedRef.current && newNodes[0]) {
          const bodyNode = newNodes.find((n: NodeItem) => n.tag === 'body') || newNodes[0];
          setSelected(bodyNode.id);
          message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: bodyNode.id });
        }
      }
      if (data.type === 'MOCKBIRD_ELEMENT_SELECTED' && data.devtoolsNodeId) {
        setSelected(data.devtoolsNodeId);
        expandAncestors(data.devtoolsNodeId, nodeMapRef.current);
        message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: data.devtoolsNodeId });
      }
      if (data.type === 'MOCKBIRD_DEVTOOLS_INSPECT_PICKED' && data.devtoolsNodeId) {
        setInspectActive(false);
        setSelected(data.devtoolsNodeId);
        expandAncestors(data.devtoolsNodeId, nodeMapRef.current);
        message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: data.devtoolsNodeId });
      }
      if (data.type === 'MOCKBIRD_DEVTOOLS_STYLES') {
        setInlineStyles(data.inlineStyles || {});
        setComputedStyles(data.computedStyles || {});
        setElementClasses(data.className || '');
        setClassInputValue(data.className || '');
      }
    };

    window.addEventListener('message', onMessage);
    const requestDom = () => message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_DOM' });
    const frame = document.querySelector<HTMLIFrameElement>(
      'iframe[data-mockbird-canvas="frame"]'
    );
    frame?.addEventListener('load', requestDom);
    requestDom();
    const timer = window.setInterval(requestDom, 2500);

    return () => {
      window.removeEventListener('message', onMessage);
      frame?.removeEventListener('load', requestDom);
      window.clearInterval(timer);
    };
  }, []);

  // Arraste de Redimensionamento do DevTools (Largura ou Altura)
  const handleDockResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    isResizingDock.current = true;
    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = dockWidth;
    const startHeight = dockHeight;

    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizingDock.current) return;
      if (dockPosition === 'right') {
        const delta = startX - ev.clientX;
        const next = Math.max(320, Math.min(850, startWidth + delta));
        setDockWidth(next);
        localStorage.setItem('mb_devtools_width', String(next));
      } else {
        const delta = startY - ev.clientY;
        const next = Math.max(160, Math.min(600, startHeight + delta));
        setDockHeight(next);
        localStorage.setItem('mb_devtools_height', String(next));
      }
    };

    const onMouseUp = () => {
      isResizingDock.current = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  };

  // Arraste de Redimensionamento Interno (Splitter Horizontal entre Árvore e Styles)
  const handleSplitResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    isResizingSplit.current = true;
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();

    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizingSplit.current) return;
      const relativeY = ev.clientY - rect.top;
      const percent = Math.max(20, Math.min(80, (relativeY / rect.height) * 100));
      setSplitPercent(percent);
      localStorage.setItem('mb_devtools_split_percent', String(percent));
    };

    const onMouseUp = () => {
      isResizingSplit.current = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  };

  const pick = (id: string) => {
    setSelected(id);
    message({ type: 'MOCKBIRD_DEVTOOLS_SELECT_NODE', nodeId: id });
    message({ type: 'MOCKBIRD_DEVTOOLS_REQUEST_STYLES', nodeId: id });
  };

  const handleNodeClick = (node: NodeItem) => {
    pick(node.id);
    if (node.childIds.length > 0) {
      setExpandedNodes((prev) => {
        const next = new Set(prev);
        if (next.has(node.id)) next.delete(node.id);
        else next.add(node.id);
        return next;
      });
    }
  };

  const handleNodeHover = (nodeId: string | null) => {
    message({ type: 'MOCKBIRD_DEVTOOLS_HOVER_NODE', nodeId });
  };

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Funções de Edição de Estilo em Tempo Real
  const updateStyleProperty = (property: string, value: string) => {
    if (!selected) return;
    setInlineStyles((prev) => {
      const next = { ...prev };
      if (!value) delete next[property];
      else next[property] = value;
      return next;
    });
    message({
      type: 'MOCKBIRD_DEVTOOLS_UPDATE_STYLE',
      nodeId: selected,
      property,
      value,
    });
  };

  const handleAddStyle = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected || !newPropName.trim()) return;
    const prop = newPropName.trim().toLowerCase();
    const val = newPropVal.trim();
    updateStyleProperty(prop, val);
    setNewPropName('');
    setNewPropVal('');
  };

  const handleUpdateClasses = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setElementClasses(classInputValue);
    message({
      type: 'MOCKBIRD_DEVTOOLS_UPDATE_CLASSES',
      nodeId: selected,
      className: classInputValue,
    });
    setEditingClass(false);
  };

  const throttle = (value: string) => {
    setProfile(value);
    message({ type: 'MOCKBIRD_DEVTOOLS_SET_THROTTLE', profile: value });
  };

  const errorCount = consoleItems.filter((i) => i.level === 'error').length;
  const warnCount = consoleItems.filter((i) => i.level === 'warn').length;

  // Renderizador recursivo fiel ao Chrome DevTools Elements Tree
  const renderElementNode = (node: NodeItem, depth: number = 0) => {
    const hasChildren = node.childIds.length > 0 || Boolean(node.textSnippet);
    const isExpanded = expandedNodes.has(node.id);
    const isSelected = selected === node.id;
    const isCustomElement = node.tag.includes('-');

    return (
      <div key={node.id} className="font-mono text-[11px] leading-5 select-text">
        <div
          onClick={() => handleNodeClick(node)}
          onDoubleClick={(e) => toggleExpand(node.id, e)}
          onMouseEnter={() => handleNodeHover(node.id)}
          onMouseLeave={() => handleNodeHover(null)}
          className={`group flex items-center hover:bg-[#282f3a] cursor-pointer py-[1px] px-1 rounded-sm transition-colors ${
            isSelected ? 'bg-[#0e3a64] text-white hover:bg-[#124474]' : 'text-[#abb2bf]'
          }`}
          style={{ paddingLeft: `${depth * 14 + 4}px` }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={(e) => toggleExpand(node.id, e)}
              className="w-4 h-4 flex items-center justify-center text-slate-400 hover:text-white shrink-0 mr-1 rounded hover:bg-white/10"
              title={isExpanded ? 'Recolher' : 'Expandir'}
            >
              {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            </button>
          ) : (
            <span className="w-4 mr-1 shrink-0" />
          )}

          <span className="text-[#80868b]">&lt;</span>
          <span className="text-[#5db0d7] font-semibold">{node.tag}</span>

          {Object.entries(node.attributes).map(([attrName, attrVal]) => {
            if (attrName === 'class' && attrVal.length > 45) {
              attrVal = attrVal.slice(0, 42) + '…';
            }
            return (
              <span key={attrName} className="ml-1.5 whitespace-nowrap">
                <span className="text-[#e29548]">{attrName}</span>
                <span className="text-[#80868b]">=</span>
                <span className="text-[#9cdcfe]">"{attrVal}"</span>
              </span>
            );
          })}

          <span className="text-[#80868b]">&gt;</span>

          {isCustomElement && (
            <span className="ml-1.5 px-1 py-[0.5px] rounded bg-[#333a44] text-[#9aa0a6] text-[9px] font-sans border border-[#444c56]">
              custom-element
            </span>
          )}

          {!isExpanded && node.textSnippet && (
            <span className="text-[#9aa0a6] ml-1 truncate max-w-[180px]">
              {node.textSnippet}
            </span>
          )}

          {!isExpanded && hasChildren && (
            <span className="text-[#80868b] mx-0.5">…</span>
          )}

          {!isExpanded && (
            <>
              <span className="text-[#80868b]">&lt;/</span>
              <span className="text-[#5db0d7] font-semibold">{node.tag}</span>
              <span className="text-[#80868b]">&gt;</span>
            </>
          )}

          {isSelected && (
            <span className="ml-2 text-slate-400 text-[10px] font-sans font-normal opacity-90">
              == $0
            </span>
          )}
        </div>

        {isExpanded && (
          <div>
            {node.childIds.map((childId) => {
              const childNode = nodeMap.get(childId);
              return childNode ? renderElementNode(childNode, depth + 1) : null;
            })}

            {node.childIds.length === 0 && node.textSnippet && (
              <div
                className="text-[#e8eaed] py-0.5 select-text hover:bg-[#282f3a]"
                style={{ paddingLeft: `${(depth + 1) * 14 + 16}px` }}
              >
                {node.textSnippet}
              </div>
            )}

            <div
              onClick={() => handleNodeClick(node)}
              onMouseEnter={() => handleNodeHover(node.id)}
              onMouseLeave={() => handleNodeHover(null)}
              className="py-[1px] px-1 hover:bg-[#282f3a] cursor-pointer"
              style={{ paddingLeft: `${depth * 14 + 20}px` }}
            >
              <span className="text-[#80868b]">&lt;/</span>
              <span className="text-[#5db0d7] font-semibold">{node.tag}</span>
              <span className="text-[#80868b]">&gt;</span>
            </div>
          </div>
        )}
      </div>
    );
  };

  const handleConsoleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!consoleInput.trim()) return;
    const cmd = consoleInput.trim();
    setConsoleItems((prev) => [...prev, { level: 'log', text: `> ${cmd}` }]);
    try {
      message({ type: 'MOCKBIRD_DEVTOOLS_EVAL', code: cmd });
    } catch (err: any) {
      setConsoleItems((prev) => [...prev, { level: 'error', text: String(err) }]);
    }
    setConsoleInput('');
  };

  return (
    <section
      data-testid="devtools-dock"
      style={{
        width: dockPosition === 'right' ? `${dockWidth}px` : '100%',
        height: dockPosition === 'bottom' ? `${dockHeight}px` : '100%',
      }}
      className={`shrink-0 bg-[#202124] text-[#abb2bf] flex flex-col font-sans select-none z-30 shadow-2xl relative ${
        dockPosition === 'right'
          ? 'border-l border-[#3c4043]'
          : 'border-t border-[#3c4043]'
      }`}
    >
      {/* Resizer da Borda da Janela DevTools (Arrastar para redimensionar a largura ou altura) */}
      <div
        onMouseDown={handleDockResizeStart}
        className={`absolute z-40 bg-transparent hover:bg-[#8ab4f8]/50 transition-colors ${
          dockPosition === 'right'
            ? 'top-0 bottom-0 -left-1.5 w-3 cursor-col-resize'
            : '-top-1.5 left-0 right-0 h-3 cursor-row-resize'
        }`}
        title="Arrastar para redimensionar o DevTools"
      />

      {/* Barra de Ferramentas Superior do Chrome DevTools */}
      <nav className="h-8 bg-[#1f1f1f] flex items-center px-1.5 border-b border-[#2d333b] text-xs shrink-0 gap-0.5">
        <button
          type="button"
          onClick={() => {
            const next = !inspectActive;
            setInspectActive(next);
            message({ type: 'MOCKBIRD_DEVTOOLS_INSPECT_MODE', active: next });
          }}
          className={`p-1 rounded transition ${
            inspectActive
              ? 'text-[#8ab4f8] bg-[#333a44] border border-[#8ab4f8]/50'
              : 'text-slate-400 hover:text-white hover:bg-[#333a44]'
          }`}
          title={inspectActive ? 'Modo de inspeção ativo' : 'Selecione um elemento na tela para inspecioná-lo (Ctrl+Shift+C)'}
        >
          <MousePointer2 size={13} />
        </button>

        <button
          type="button"
          className="p-1 rounded hover:bg-[#333a44] text-slate-400 hover:text-white transition"
          title="Alternar barra de ferramentas do dispositivo (Ctrl+Shift+M)"
        >
          <Smartphone size={13} />
        </button>

        <div className="w-px h-4 bg-[#3c4043] mx-1" />

        {(
          [
            { id: 'elements', label: 'Elements', testId: 'devtools-tab-elements' },
            { id: 'console', label: 'Console', testId: 'devtools-tab-console' },
            { id: 'network', label: 'Network', testId: 'devtools-tab-network' },
          ] as const
        ).map(({ id, label, testId }) => {
          const isActive = tab === id;
          return (
            <button
              key={id}
              data-testid={testId}
              onClick={() => setTab(id)}
              className={`px-2.5 py-1 text-[11px] font-medium transition relative ${
                isActive
                  ? 'text-white font-semibold'
                  : 'text-[#9aa0a6] hover:text-slate-200 hover:bg-white/5'
              }`}
            >
              {label}
              {isActive && (
                <div className="absolute bottom-0 left-0 right-0 h-[2px] bg-[#8ab4f8]" />
              )}
            </button>
          );
        })}

        {/* Lado Direito da Barra DevTools */}
        <div className="ml-auto flex items-center gap-1">
          {errorCount > 0 && (
            <div
              className="flex items-center gap-1 text-[10px] text-rose-400 bg-rose-950/40 px-1.5 py-0.5 rounded cursor-pointer"
              onClick={() => setTab('console')}
              title={`${errorCount} erros`}
            >
              <AlertCircle size={11} />
              <span>{errorCount}</span>
            </div>
          )}

          {warnCount > 0 && (
            <div
              className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-950/40 px-1.5 py-0.5 rounded cursor-pointer"
              onClick={() => setTab('console')}
              title={`${warnCount} avisos`}
            >
              <AlertTriangle size={11} />
              <span>{warnCount}</span>
            </div>
          )}

          <button
            type="button"
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-[#333a44] transition"
            title="Configurações"
          >
            <Settings size={13} />
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setShowDockMenu((v) => !v)}
              className={`p-1 rounded transition ${
                showDockMenu ? 'bg-[#333a44] text-white' : 'text-slate-400 hover:text-white hover:bg-[#333a44]'
              }`}
              title="Posição do DevTools"
            >
              <MoreVertical size={13} />
            </button>

            {showDockMenu && (
              <div className="absolute right-0 top-full mt-1 w-48 rounded-lg bg-[#292a2d] border border-[#3c4043] p-1.5 shadow-2xl z-50 text-xs space-y-1">
                <span className="text-[10px] uppercase font-semibold text-slate-400 px-2 py-1 block">
                  Posição do DevTools
                </span>
                <button
                  type="button"
                  onClick={() => {
                    onDockChange?.('right');
                    setShowDockMenu(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-left transition ${
                    dockPosition === 'right' ? 'bg-[#8ab4f8]/20 text-[#8ab4f8]' : 'text-slate-300 hover:bg-white/5'
                  }`}
                >
                  <PanelRight size={13} />
                  <span>Fixar na lateral direita</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onDockChange?.('bottom');
                    setShowDockMenu(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-left transition ${
                    dockPosition === 'bottom' ? 'bg-[#8ab4f8]/20 text-[#8ab4f8]' : 'text-slate-300 hover:bg-white/5'
                  }`}
                >
                  <PanelBottom size={13} />
                  <span>Fixar na parte inferior</span>
                </button>
              </div>
            )}
          </div>

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded text-slate-400 hover:text-white hover:bg-[#333a44] transition"
              title="Fechar DevTools (F12)"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </nav>

      {/* Conteúdo da Aba */}
      <div ref={containerRef} className="flex-1 overflow-hidden flex flex-col min-h-0 bg-[#202124] relative">
        {/* 1. ELEMENTS PANEL (ÁRVORE DOM EM CIMA, STYLES EMBAIXO COM RESIZER) */}
        {tab === 'elements' && (
          <div className="flex-1 flex flex-col h-full overflow-hidden">
            {/* PARTE SUPERIOR: Árvore DOM */}
            <div
              style={{ height: `${splitPercent}%` }}
              className="overflow-auto p-2 min-h-[80px]"
            >
              <div className="text-[10px] text-slate-500 font-mono mb-1.5">
                #adopted-style-sheets
                <br />
                &lt;!DOCTYPE html&gt;
              </div>
              {rootNodes.map((node) => renderElementNode(node, 0))}
            </div>

            {/* SPLITTER HORIZONTAL REDIMENSIONÁVEL (Arrastar para cima/baixo como no Chrome) */}
            <div
              onMouseDown={handleSplitResizeStart}
              className="h-1 bg-[#2d333b] hover:bg-[#8ab4f8] transition-colors cursor-row-resize shrink-0 relative group"
              title="Arrastar para redimensionar o painel Styles"
            >
              <div className="absolute inset-x-0 -top-1 -bottom-1" />
            </div>

            {/* PARTE INFERIOR: PAINEL STYLES & COMPUTED (100% como no Chrome DevTools!) */}
            <div
              style={{ height: `${100 - splitPercent}%` }}
              className="bg-[#1e1f22] flex flex-col min-h-[90px] border-t border-[#2d333b] overflow-hidden"
            >
              {/* Abas do Painel Inferior: Styles | Computed */}
              <div className="h-7 bg-[#202124] border-b border-[#2d333b] px-2 flex items-center justify-between text-xs shrink-0">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    data-testid="devtools-tab-styles"
                    onClick={() => setElementsSubTab('styles')}
                    className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition ${
                      elementsSubTab === 'styles'
                        ? 'bg-[#333a44] text-[#8ab4f8]'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Styles
                  </button>
                  <button
                    type="button"
                    onClick={() => setElementsSubTab('computed')}
                    className={`px-2.5 py-0.5 rounded text-[11px] font-medium transition ${
                      elementsSubTab === 'computed'
                        ? 'bg-[#333a44] text-[#8ab4f8]'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Computed
                  </button>
                </div>

                <span className="text-[10px] font-mono text-[#8ab4f8] truncate max-w-[150px]">
                  {selected ? `<${nodeMap.get(selected)?.tag}>` : 'nenhum'}
                </span>
              </div>

              {/* Conteúdo: Sub-aba STYLES (Editável em tempo real!) */}
              {elementsSubTab === 'styles' && (
                <div className="flex-1 overflow-auto p-3 font-mono text-[11px] space-y-3">
                  {selected ? (
                    <>
                      {/* 1. element.style { ... } (Editável!) */}
                      <div className="bg-[#202124] p-2.5 rounded-lg border border-[#2d333b] shadow-sm">
                        <div className="flex items-center justify-between text-[#8ab4f8] font-semibold mb-1.5">
                          <span>element.style &#123;</span>
                          <span className="text-[9px] font-sans text-slate-500 font-normal">
                            clique no valor para editar
                          </span>
                        </div>

                        {/* Lista de Declarações Inline Existentes */}
                        <div className="pl-3 space-y-1 text-slate-300">
                          {Object.entries(inlineStyles).map(([prop, val]) => (
                            <div key={prop} className="flex items-center gap-1.5 group">
                              <span className="text-[#9cdcfe] shrink-0">{prop}</span>
                              <span className="text-slate-500">:</span>
                              <input
                                type="text"
                                value={val}
                                onChange={(e) => updateStyleProperty(prop, e.target.value)}
                                className="bg-transparent text-[#ce9178] px-1 py-0.5 rounded hover:bg-[#282f3a] focus:bg-[#161b22] focus:border-[#8ab4f8] border border-transparent outline-none flex-1 font-mono text-[11px]"
                                title="Editar valor do estilo"
                              />
                              <span className="text-slate-500">;</span>
                              <button
                                type="button"
                                onClick={() => updateStyleProperty(prop, '')}
                                className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-rose-400 transition ml-auto"
                                title="Remover propriedade"
                              >
                                <Trash2 size={11} />
                              </button>
                            </div>
                          ))}

                          {/* Formulário Inline para Adicionar Nova Propriedade */}
                          <form onSubmit={handleAddStyle} className="flex items-center gap-1 pt-1.5 border-t border-[#2d333b]/60">
                            <input
                              placeholder="+ propriedade (ex: color)"
                              value={newPropName}
                              onChange={(e) => setNewPropName(e.target.value)}
                              className="w-32 bg-[#161b22] text-[#9cdcfe] px-1.5 py-0.5 rounded border border-[#30363d] focus:border-[#8ab4f8] outline-none text-[11px]"
                            />
                            <span className="text-slate-500">:</span>
                            <input
                              placeholder="valor (ex: red)"
                              value={newPropVal}
                              onChange={(e) => setNewPropVal(e.target.value)}
                              className="flex-1 bg-[#161b22] text-[#ce9178] px-1.5 py-0.5 rounded border border-[#30363d] focus:border-[#8ab4f8] outline-none text-[11px]"
                            />
                            <button
                              type="submit"
                              disabled={!newPropName.trim()}
                              className="p-1 rounded bg-[#333a44] text-[#8ab4f8] hover:bg-[#444c56] disabled:opacity-40 transition"
                              title="Adicionar regra de estilo"
                            >
                              <Plus size={12} />
                            </button>
                          </form>
                        </div>

                        <div className="text-[#8ab4f8] font-semibold mt-1.5">&#125;</div>
                      </div>

                      {/* 2. Classes CSS do Elemento (Editáveis!) */}
                      <div className="bg-[#202124] p-2.5 rounded-lg border border-[#2d333b]">
                        <div className="flex items-center justify-between text-[#e29548] font-semibold mb-1">
                          <span>.classes &#123;</span>
                          {!editingClass ? (
                            <button
                              type="button"
                              onClick={() => setEditingClass(true)}
                              className="text-[10px] font-sans text-[#8ab4f8] hover:underline"
                            >
                              Editar classes
                            </button>
                          ) : null}
                        </div>

                        {editingClass ? (
                          <form onSubmit={handleUpdateClasses} className="space-y-1.5 py-1">
                            <input
                              autoFocus
                              value={classInputValue}
                              onChange={(e) => setClassInputValue(e.target.value)}
                              placeholder="ex: sessao-scrim px-4 py-8 bg-slate-900"
                              className="w-full bg-[#161b22] text-[#9cdcfe] px-2 py-1 rounded border border-[#8ab4f8] outline-none font-mono text-[11px]"
                            />
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => {
                                  setClassInputValue(elementClasses);
                                  setEditingClass(false);
                                }}
                                className="px-2 py-0.5 rounded text-[10px] text-slate-400 hover:text-white"
                              >
                                Cancelar
                              </button>
                              <button
                                type="submit"
                                className="px-2 py-0.5 rounded text-[10px] bg-[#8ab4f8] text-black font-semibold"
                              >
                                Aplicar
                              </button>
                            </div>
                          </form>
                        ) : (
                          <div
                            onClick={() => setEditingClass(true)}
                            className="pl-3 text-slate-300 text-[11px] cursor-pointer hover:bg-[#282f3a] py-1 rounded"
                            title="Clique para editar classes"
                          >
                            {elementClasses ? (
                              <span className="text-[#9cdcfe] break-all">{elementClasses}</span>
                            ) : (
                              <span className="text-slate-500 italic">nenhuma classe CSS</span>
                            )}
                          </div>
                        )}

                        <div className="text-[#e29548] font-semibold mt-1">&#125;</div>
                      </div>
                    </>
                  ) : (
                    <div className="text-slate-500 text-center py-6 text-[11px]">
                      Selecione um elemento para inspecionar e editar regras de estilo.
                    </div>
                  )}
                </div>
              )}

              {/* Conteúdo: Sub-aba COMPUTED (Fiel à imagem 5 do Chrome DevTools!) */}
              {elementsSubTab === 'computed' && (
                <div className="flex-1 overflow-hidden flex flex-col p-2">
                  <div className="flex items-center gap-1.5 bg-[#161b22] px-2 py-1 rounded border border-[#30363d] mb-2 text-xs">
                    <Search size={12} className="text-slate-500" />
                    <input
                      placeholder="Filtrar propriedades..."
                      value={computedFilter}
                      onChange={(e) => setComputedFilter(e.target.value)}
                      className="bg-transparent text-slate-200 outline-none w-full text-[11px]"
                    />
                  </div>
                  <div className="flex-1 overflow-auto bg-[#202124] p-3 rounded-lg border border-[#2d333b] font-mono text-[11px] select-text">
                    <div className="text-slate-400 font-sans text-[11px] font-semibold mb-2 flex items-center justify-between border-b border-[#2d333b] pb-1.5">
                      <span className="text-[#8ab4f8]">Valores Computados do Navegador</span>
                      <span className="text-[10px] text-slate-500 font-normal">
                        {Object.keys(computedStyles).length} propriedades
                      </span>
                    </div>
                    <div className="space-y-0.5">
                      {Object.entries(computedStyles)
                        .filter(([k]) => !computedFilter || k.toLowerCase().includes(computedFilter.toLowerCase()))
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([prop, val]) => (
                          <div
                            key={prop}
                            onClick={() => updateStyleProperty(prop, val)}
                            className="flex items-center pl-2 py-[2px] hover:bg-[#282f3a] rounded cursor-pointer group"
                            title="Clique para adicionar/editar esta propriedade em element.style"
                          >
                            <span className="text-[#9cdcfe] shrink-0 font-medium">{prop}</span>
                            <span className="text-[#80868b] mr-1.5">:</span>
                            <span className="text-[#ce9178] truncate" title={val}>{val}</span>
                            <span className="opacity-0 group-hover:opacity-100 text-[9px] text-[#8ab4f8] ml-auto font-sans">
                              + editar
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 2. CONSOLE PANEL */}
        {tab === 'console' && (
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="h-7 bg-[#1f1f1f] border-b border-[#2d333b] px-2 flex items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setConsoleItems([])}
                  className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/10"
                  title="Limpar console"
                >
                  <Ban size={12} />
                </button>
                <div className="flex items-center gap-1 bg-[#161b22] px-2 py-0.5 rounded text-[11px] text-slate-300 border border-[#30363d]">
                  <Search size={11} className="text-slate-500" />
                  <input
                    placeholder="Filtrar"
                    value={consoleFilter}
                    onChange={(e) => setConsoleFilter(e.target.value)}
                    className="bg-transparent outline-none w-28 text-[11px]"
                  />
                </div>
              </div>
              <span className="text-[10px] text-slate-500 font-mono">
                {consoleItems.length} logs
              </span>
            </div>

            <div className="flex-1 overflow-auto p-2 font-mono text-[11px] space-y-1">
              {consoleItems.length === 0 && (
                <div className="text-slate-500 italic py-4">Console vazio.</div>
              )}
              {consoleItems
                .filter((item) => !consoleFilter || item.text.toLowerCase().includes(consoleFilter.toLowerCase()))
                .map((item, index) => {
                const isErr = item.level === 'error';
                const isWarn = item.level === 'warn';
                return (
                  <div
                    key={index}
                    className={`flex items-start gap-2 py-1 px-1.5 rounded ${
                      isErr
                        ? 'bg-rose-950/20 text-rose-300 border-l-2 border-rose-500'
                        : isWarn
                        ? 'bg-amber-950/20 text-amber-300 border-l-2 border-amber-500'
                        : 'text-slate-300 hover:bg-white/5'
                    }`}
                  >
                    <span className="text-slate-500 select-none text-[10px] mt-0.5">&gt;</span>
                    <span className="flex-1 break-all whitespace-pre-wrap">{item.text}</span>
                  </div>
                );
              })}
            </div>

            <form
              onSubmit={handleConsoleSubmit}
              className="h-8 bg-[#1f1f1f] border-t border-[#2d333b] px-2 flex items-center gap-1.5 font-mono text-xs"
            >
              <span className="text-[#8ab4f8] select-none font-bold">&gt;</span>
              <input
                value={consoleInput}
                onChange={(e) => setConsoleInput(e.target.value)}
                placeholder="Executar código no contexto da tela…"
                className="flex-1 bg-transparent text-slate-100 outline-none text-[11px]"
              />
            </form>
          </div>
        )}

        {/* 3. NETWORK PANEL */}
        {tab === 'network' && (
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="h-7 bg-[#1f1f1f] border-b border-[#2d333b] px-2 flex items-center justify-between text-xs">
              <span className="text-[11px] text-slate-400 font-medium">Requisições de Rede</span>
              <select
                data-testid="network-type"
                value={profile}
                onChange={(event) => throttle(event.target.value)}
                className="bg-[#161b22] border border-[#30363d] px-1.5 py-0.5 rounded text-[11px] text-slate-200"
              >
                <option value="off">Sem throttling</option>
                <option value="slow3g">Slow 3G</option>
                <option value="4g">4G</option>
              </select>
            </div>
            <div className="flex-1 overflow-auto font-mono text-[11px]">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#2d333b] text-slate-500 text-[10px] bg-[#161b22]">
                    <th className="py-1 px-2">Name</th>
                    <th className="py-1 px-2">Method</th>
                    <th className="py-1 px-2">Status</th>
                    <th className="py-1 px-2">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {network.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="py-6 text-center text-slate-500 italic">
                        Nenhuma requisição registrada.
                      </td>
                    </tr>
                  ) : (
                    network.map((item, index) => (
                      <tr
                        key={index}
                        className="border-b border-[#2d333b]/40 hover:bg-[#282f3a]"
                      >
                        <td className="py-1 px-2 truncate max-w-[160px] text-slate-200" title={item.url}>
                          {item.url.split('/').pop() || item.url}
                        </td>
                        <td className="py-1 px-2 font-bold text-[#8ab4f8]">{item.method}</td>
                        <td className="py-1 px-2">
                          <span className={item.ok ? 'text-emerald-400' : 'text-rose-400'}>
                            {item.status || (item.ok ? 200 : 'err')}
                          </span>
                        </td>
                        <td className="py-1 px-2 text-slate-400">{item.duration}ms</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
