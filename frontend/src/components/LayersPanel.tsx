import React, { useMemo, useState } from 'react';
import { 
  Layers, 
  ChevronRight, 
  ChevronDown, 
  Eye, 
  Copy, 
  Trash2, 
  Search,
  Type,
  Square,
  MousePointerClick,
  Image as ImageIcon,
  Table as TableIcon,
  FormInput
} from 'lucide-react';

export interface DomNodeItem {
  id: string; // mbId or generated
  tag: string;
  name: string;
  classes: string;
  snippet: string;
  children: DomNodeItem[];
  depth: number;
}

interface LayersPanelProps {
  htmlContent: string;
  selectedMbId?: string | null;
  onSelectMbId: (mbId: string) => void;
  onToggleVisibility: (mbId: string) => void;
  onDuplicate: (mbId: string) => void;
  onDelete: (mbId: string) => void;
}

function parseDomTree(html: string): DomNodeItem[] {
  if (!html || !html.trim()) return [];
  try {
    const parser = new DOMParser();
    let root: Element | null = null;
    if (html.includes('<html') || html.includes('<!DOCTYPE')) {
      const doc = parser.parseFromString(html, 'text/html');
      root = doc.body || doc.documentElement;
    } else {
      const doc = parser.parseFromString(`<div>${html}</div>`, 'text/html');
      root = doc.body.firstElementChild;
    }
    if (!root) return [];

    let counter = 0;
    function traverse(node: Element, depth: number): DomNodeItem[] {
      const items: DomNodeItem[] = [];
      Array.from(node.children).forEach((el) => {
        const tag = el.tagName.toLowerCase();
        // Ignora scripts, estilos e tags de cabeçalho / runtime
        if (['script', 'style', 'meta', 'link', 'noscript', 'head'].includes(tag)) return;
        const rawId = el.getAttribute('data-mb-id') || el.id || '';
        if (rawId.startsWith('mb-') || rawId.startsWith('mockbird-')) return;

        counter++;
        const mbId = rawId || `node-${counter}-${tag}`;
        
        let text = (el.textContent || '').trim().replace(/\s+/g, ' ');
        if (text.length > 25) text = text.substring(0, 25) + '…';

        const item: DomNodeItem = {
          id: mbId,
          tag,
          name: rawId || tag,
          classes: Array.from(el.classList).slice(0, 2).join(' '),
          snippet: text,
          depth,
          children: traverse(el, depth + 1),
        };
        items.push(item);
      });
      return items;
    }

    return traverse(root, 0);
  } catch (err) {
    console.error('Erro ao parsear árvore de camadas:', err);
    return [];
  }
}

function getTagIcon(tag: string) {
  switch (tag) {
    case 'h1':
    case 'h2':
    case 'h3':
    case 'h4':
    case 'p':
    case 'span':
      return Type;
    case 'button':
    case 'a':
      return MousePointerClick;
    case 'img':
    case 'svg':
      return ImageIcon;
    case 'table':
      return TableIcon;
    case 'form':
    case 'input':
    case 'select':
      return FormInput;
    default:
      return Square;
  }
}

export const LayersPanel: React.FC<LayersPanelProps> = ({
  htmlContent,
  selectedMbId,
  onSelectMbId,
  onToggleVisibility,
  onDuplicate,
  onDelete,
}) => {
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const tree = useMemo(() => parseDomTree(htmlContent), [htmlContent]);

  const toggleCollapse = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const renderItem = (item: DomNodeItem) => {
    const isSelected = selectedMbId === item.id;
    const hasChildren = item.children.length > 0;
    const isCollapsed = collapsed[item.id];
    const Icon = getTagIcon(item.tag);

    const matchesSearch =
      !search ||
      item.tag.includes(search.toLowerCase()) ||
      item.id.toLowerCase().includes(search.toLowerCase()) ||
      item.snippet.toLowerCase().includes(search.toLowerCase());

    return (
      <div key={item.id} className="flex flex-col">
        {matchesSearch && (
          <div
            onClick={() => onSelectMbId(item.id)}
            style={{ paddingLeft: `${Math.max(8, item.depth * 14 + 8)}px` }}
            className={`group flex items-center justify-between py-1.5 pr-2 rounded-lg cursor-pointer text-xs transition-colors ${
              isSelected
                ? 'bg-mockbird-blue/20 text-white font-medium ring-1 ring-mockbird-cyan/50'
                : 'text-slate-300 hover:bg-mockbird-card hover:text-white'
            }`}
          >
            <div className="flex items-center gap-1.5 min-w-0">
              {hasChildren ? (
                <button
                  type="button"
                  onClick={(e) => toggleCollapse(item.id, e)}
                  className="p-0.5 text-slate-500 hover:text-slate-200 transition"
                  aria-label="Expandir ou recolher"
                >
                  {isCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                </button>
              ) : (
                <span className="w-3.5" />
              )}

              <Icon size={13} className={isSelected ? 'text-mockbird-cyan' : 'text-slate-500'} />

              <span className="font-mono text-[11px] text-slate-400">&lt;{item.tag}&gt;</span>

              {item.classes && (
                <span className="text-[10px] text-slate-500 truncate max-w-[80px]">
                  .{item.classes.replace(/\s+/g, '.')}
                </span>
              )}

              {item.snippet && (
                <span className="text-[10px] text-slate-400 truncate max-w-[90px] font-sans">
                  "{item.snippet}"
                </span>
              )}
            </div>

            {/* Ações rápidas na camada */}
            <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 shrink-0">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleVisibility(item.id);
                }}
                className="p-1 text-slate-400 hover:text-white rounded"
                title="Ocultar / Exibir"
              >
                <Eye size={12} />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDuplicate(item.id);
                }}
                className="p-1 text-slate-400 hover:text-mockbird-cyan rounded"
                title="Duplicar elemento"
              >
                <Copy size={12} />
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(item.id);
                }}
                className="p-1 text-slate-400 hover:text-rose-400 rounded"
                title="Excluir elemento"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        )}

        {hasChildren && !isCollapsed && (
          <div className="flex flex-col">
            {item.children.map((child) => renderItem(child))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full p-4 space-y-3 shrink-0 select-none shadow-2xl">
      <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
        <h3 className="font-bold text-xs uppercase tracking-wider flex items-center gap-2 text-white">
          <Layers className="h-4 w-4 text-mockbird-cyan" />
          Árvore de Camadas
        </h3>
        <span className="text-[10px] text-slate-500 font-mono">
          DOM Tree
        </span>
      </div>

      {/* Busca rápida de elementos */}
      <div className="relative">
        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filtrar por tag, id ou texto…"
          className="w-full pl-8 pr-3 py-1.5 text-xs bg-mockbird-bg border border-mockbird-border rounded-lg text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-mockbird-cyan"
        />
      </div>

      <p className="text-[11px] text-slate-400">
        Navegue na hierarquia de componentes da tela. Clique para inspecionar ou alterar visibilidade.
      </p>

      {/* Árvore hierárquica */}
      <div className="flex-1 overflow-y-auto space-y-0.5 border border-mockbird-border/60 rounded-xl p-2 bg-mockbird-bg">
        {tree.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">
            Nenhum elemento encontrado na tela.
          </div>
        ) : (
          tree.map((node) => renderItem(node))
        )}
      </div>
    </div>
  );
};
