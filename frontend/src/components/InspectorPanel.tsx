import React, { useEffect, useState } from 'react';
import { 
  Eye, 
  Type, 
  Square, 
  ArrowUp, 
  ArrowDown, 
  Copy, 
  Trash2,
  Navigation,
  Layers,
  Bell,
  Database
} from 'lucide-react';

/** Converte rgb()/rgba() do computed style para o #rrggbb aceito pelo input color. */
function toHexColor(value?: string): string {
  if (!value) return '#000000';
  const match = value.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
  if (match) {
    return '#' + [match[1], match[2], match[3]]
      .map((part) => Number(part).toString(16).padStart(2, '0'))
      .join('');
  }
  return /^#[0-9a-f]{6}$/i.test(value) ? value : '#000000';
}

export interface SelectedElementData {
  mbId: string;
  tag: string;
  leaf?: boolean;
  selector?: string;
  dataGo?: string;
  dataToast?: string;
  dataOverlay?: string;
  dataClose?: string | boolean;
  dataMock?: string;
  styles: {
    text?: string;
    bg?: string;
    color?: string;
    padding?: string;
    margin?: string;
    fontSize?: string;
    borderRadius?: string;
  };
}

interface InspectorPanelProps {
  selectedElement: SelectedElementData | null;
  screens?: Array<{ id: string; name: string; slug: string }>;
  onApplyStylePatch: (patch: any) => void;
  onApplyAttributes?: (attributes: Record<string, string | null>) => void;
  onSendAction: (actionType: string) => void;
  onClose?: () => void;
}

export const InspectorPanel: React.FC<InspectorPanelProps> = ({
  selectedElement,
  screens = [],
  onApplyStylePatch,
  onApplyAttributes,
  onSendAction
}) => {
  const initialBg = selectedElement?.styles.bg || (selectedElement?.styles as any)?.backgroundColor;
  const [text, setText] = useState(selectedElement?.styles.text ?? '');
  const [bg, setBg] = useState(toHexColor(initialBg));
  const [imgSrc, setImgSrc] = useState('');
  const [imgAlt, setImgAlt] = useState('');
  const [dataGo, setDataGo] = useState(selectedElement?.dataGo ?? '');
  const [dataOverlay, setDataOverlay] = useState(selectedElement?.dataOverlay ?? '');
  const [dataToast, setDataToast] = useState(selectedElement?.dataToast ?? '');
  const [dataClose, setDataClose] = useState(Boolean(selectedElement?.dataClose));
  const [dataMock, setDataMock] = useState(selectedElement?.dataMock ?? '');

  useEffect(() => {
    const nextBg = selectedElement?.styles.bg || (selectedElement?.styles as any)?.backgroundColor;
    setText(selectedElement?.styles.text ?? '');
    setBg(toHexColor(nextBg));
    setDataGo(selectedElement?.dataGo ?? '');
    setDataOverlay(selectedElement?.dataOverlay ?? '');
    setDataToast(selectedElement?.dataToast ?? '');
    setDataClose(Boolean(selectedElement?.dataClose));
    setDataMock(selectedElement?.dataMock ?? '');
  }, [
    selectedElement?.mbId,
    selectedElement?.styles.text,
    selectedElement?.styles.bg,
    (selectedElement?.styles as any)?.backgroundColor,
    selectedElement?.dataGo,
    selectedElement?.dataOverlay,
    selectedElement?.dataToast,
    selectedElement?.dataClose,
    selectedElement?.dataMock
  ]);

  return (
    <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full overflow-y-auto shrink-0 space-y-5 p-4 select-none shadow-2xl">
      {selectedElement && (
        <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
          <span className="text-[11px] font-medium text-slate-400">Elemento selecionado</span>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-mockbird-blue/10 text-mockbird-cyan border border-mockbird-blue/20">
            &lt;{selectedElement.tag}&gt;
          </span>
        </div>
      )}

      {selectedElement ? (
        <div className="space-y-4">
          
          {/* Ações de Reordenação e Estrutura */}
          <div className="space-y-1.5">
            <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Estrutura & Posição</span>
            <div className="grid grid-cols-4 gap-1 bg-mockbird-card p-1 rounded-lg border border-mockbird-border">
              <button
                type="button"
                onClick={() => onSendAction('MOCKBIRD_MOVE_UP')}
                className="p-1.5 rounded hover:bg-mockbird-surface text-slate-300 hover:text-white flex items-center justify-center transition-colors"
                title="Subir Posição (Antes)"
              >
                <ArrowUp size={14} />
              </button>
              <button
                type="button"
                onClick={() => onSendAction('MOCKBIRD_MOVE_DOWN')}
                className="p-1.5 rounded hover:bg-mockbird-surface text-slate-300 hover:text-white flex items-center justify-center transition-colors"
                title="Descer Posição (Depois)"
              >
                <ArrowDown size={14} />
              </button>
              <button
                type="button"
                onClick={() => onSendAction('MOCKBIRD_DUPLICATE')}
                className="p-1.5 rounded hover:bg-mockbird-surface text-slate-300 hover:text-white flex items-center justify-center transition-colors"
                title="Duplicar Elemento"
              >
                <Copy size={14} />
              </button>
              <button
                type="button"
                onClick={() => onSendAction('MOCKBIRD_DELETE')}
                className="p-1.5 rounded hover:bg-rose-500/20 text-rose-400 hover:text-rose-300 flex items-center justify-center transition-colors"
                title="Excluir Elemento"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>

          <div className="space-y-1">
            <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Identificador Único</span>
            <p className="font-mono text-xs text-slate-300 bg-mockbird-card p-2 rounded-lg border border-mockbird-border break-all">
              {selectedElement.mbId}
            </p>
          </div>

          {selectedElement.tag === 'img' && (
            <div className="space-y-2 p-2.5 rounded-lg bg-mockbird-card border border-mockbird-border">
              <span className="text-[10px] uppercase font-semibold text-mockbird-cyan tracking-wider">
                Configurações da Imagem
              </span>
              <div className="space-y-1">
                <label className="text-[11px] text-slate-300 font-medium">URL da Imagem (src)</label>
                <input
                  type="text"
                  placeholder="https://... ou /api/assets/..."
                  value={imgSrc}
                  onChange={(e) => {
                    setImgSrc(e.target.value);
                    onApplyAttributes?.({ src: e.target.value });
                  }}
                  className="w-full px-2.5 py-1.5 text-xs rounded bg-mockbird-bg border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan font-mono"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-slate-300 font-medium">Texto Alternativo (alt)</label>
                <input
                  type="text"
                  placeholder="Descrição da imagem"
                  value={imgAlt}
                  onChange={(e) => {
                    setImgAlt(e.target.value);
                    onApplyAttributes?.({ alt: e.target.value });
                  }}
                  className="w-full px-2.5 py-1.5 text-xs rounded bg-mockbird-bg border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
                />
              </div>
            </div>
          )}

          {selectedElement.styles.text !== undefined && selectedElement.leaf !== false && selectedElement.tag !== 'img' && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Type className="h-3.5 w-3.5 text-mockbird-cyan" /> Texto
              </label>
              <textarea 
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  onApplyStylePatch({ text: e.target.value });
                }}
                className="w-full px-3 py-2 text-xs rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
                rows={2}
              />
            </div>
          )}

          {selectedElement.leaf === false && (
            <p className="text-[11px] text-slate-400 bg-mockbird-card border border-mockbird-border rounded-lg p-2.5 leading-relaxed">
              Este elemento tem filhos. Dê um duplo clique no canvas para editar o texto sem perder a estrutura.
            </p>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Square className="h-3.5 w-3.5 text-mockbird-cyan" /> Cor de Fundo
            </label>
            <div className="flex items-center gap-2">
              <input 
                type="color" 
                value={bg}
                onChange={(e) => {
                  setBg(e.target.value);
                  onApplyStylePatch({ bg: e.target.value });
                }}
                className="h-7 w-8 rounded cursor-pointer bg-transparent border-0 p-0"
              />
              <button 
                onClick={() => onApplyStylePatch({ bg: 'var(--color-primary)' })}
                className="flex-1 py-1 px-2 text-[11px] rounded bg-mockbird-card border border-mockbird-border text-mockbird-cyan font-semibold hover:bg-slate-700 transition"
              >
                Usar --color-primary
              </button>
            </div>
          </div>

          <div className="pt-2 border-t border-mockbird-border space-y-2">
            <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Ações de Estilo</span>
            <div className="grid grid-cols-2 gap-1.5">
              <button 
                onClick={() => onApplyStylePatch({ borderRadius: '12px' })}
                className="py-1.5 px-2 rounded-lg bg-mockbird-card border border-mockbird-border text-[11px] font-semibold text-slate-300 hover:text-white hover:bg-slate-700 transition text-center"
              >
                Arredondar
              </button>
              <button 
                onClick={() => onApplyStylePatch({ padding: '16px' })}
                className="py-1.5 px-2 rounded-lg bg-mockbird-card border border-mockbird-border text-[11px] font-semibold text-slate-300 hover:text-white hover:bg-slate-700 transition text-center"
              >
                Padding Largo
              </button>
            </div>
          </div>

          {/* Interatividade & Comportamento Mock */}
          <div className="pt-3 border-t border-mockbird-border space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Ação ao Clicar (Mock)</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                interativo
              </span>
            </div>

            {/* Navegar para tela */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Navigation className="h-3.5 w-3.5 text-mockbird-cyan" /> Navegar para Tela
              </label>
              <select
                value={dataGo}
                onChange={(e) => {
                  const val = e.target.value;
                  setDataGo(val);
                  onApplyAttributes?.({ 'data-go': val || null });
                }}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
              >
                <option value="">(Nenhuma navegação)</option>
                {screens.map((sc) => (
                  <option key={sc.id} value={sc.slug || sc.name}>
                    {sc.name} ({sc.slug || 'slug'})
                  </option>
                ))}
              </select>
            </div>

            {/* Abrir Modal / Overlay */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Layers className="h-3.5 w-3.5 text-mockbird-cyan" /> Abrir Modal / Overlay
              </label>
              <input
                type="text"
                value={dataOverlay}
                placeholder="ID ou seletor (ex: #modal-lead)"
                onChange={(e) => {
                  const val = e.target.value;
                  setDataOverlay(val);
                  onApplyAttributes?.({ 'data-overlay': val || null });
                }}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
              />
            </div>

            {/* Fechar Modal */}
            <div className="flex items-center gap-2 pt-0.5">
              <input
                type="checkbox"
                id="mb-data-close"
                checked={dataClose}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setDataClose(checked);
                  onApplyAttributes?.({ 'data-close': checked ? '' : null });
                }}
                className="h-3.5 w-3.5 rounded border-mockbird-border bg-mockbird-card text-mockbird-blue focus:ring-0 cursor-pointer"
              />
              <label htmlFor="mb-data-close" className="text-xs text-slate-300 cursor-pointer select-none">
                Fecha o modal / overlay ativo ao clicar
              </label>
            </div>

            {/* Notificação Toast */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Bell className="h-3.5 w-3.5 text-mockbird-cyan" /> Exibir Notificação (Toast)
              </label>
              <input
                type="text"
                value={dataToast}
                placeholder="Ex: Registro salvo com sucesso!"
                onChange={(e) => {
                  const val = e.target.value;
                  setDataToast(val);
                  onApplyAttributes?.({ 'data-toast': val || null });
                }}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
              />
            </div>

            {/* Dado Dinâmico Mock */}
            <div className="space-y-1 pt-1">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5 text-mockbird-cyan" /> Dado Mock Vinculado
              </label>
              <input
                type="text"
                value={dataMock}
                placeholder="Caminho do dado (ex: user.name, revenue)"
                onChange={(e) => {
                  const val = e.target.value;
                  setDataMock(val);
                  onApplyAttributes?.({ 'data-mock': val || null });
                }}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan font-mono"
              />
              <p className="text-[10px] text-slate-500 leading-tight">
                Substituído dinamicamente pelo cenário selecionado.
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-slate-400 space-y-2">
          <Eye className="h-8 w-8 stroke-1 text-slate-500" />
          <p className="text-xs">Clique em qualquer elemento do canvas para reordenar, duplicar ou editar estilos.</p>
        </div>
      )}
    </div>
  );
};

