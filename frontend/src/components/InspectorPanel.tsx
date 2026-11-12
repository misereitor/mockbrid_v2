import React, { useEffect, useState } from 'react';
import { 
  Eye, 
  Type, 
  Square, 
  ArrowUp, 
  ArrowDown, 
  Copy, 
  Trash2,
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
  onApplyStylePatch: (patch: any) => void;
  onSendAction: (actionType: string) => void;
  onClose?: () => void;
}

export const InspectorPanel: React.FC<InspectorPanelProps> = ({
  selectedElement,
  onApplyStylePatch,
  onSendAction
}) => {
  // O estado do elemento no pai só é atualizado ao selecionar; manter cópias
  // locais evita que os campos voltem ao valor antigo a cada tecla digitada.
  const [text, setText] = useState(selectedElement?.styles.text ?? '');
  const [bg, setBg] = useState(toHexColor(selectedElement?.styles.bg));

  useEffect(() => {
    setText(selectedElement?.styles.text ?? '');
    setBg(toHexColor(selectedElement?.styles.bg));
  }, [selectedElement?.mbId, selectedElement?.styles.text, selectedElement?.styles.bg]);

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

          {selectedElement.styles.text !== undefined && selectedElement.leaf !== false && (
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

