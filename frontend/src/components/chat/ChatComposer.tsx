import React from 'react';
import { Loader2, Target, Workflow, X } from 'lucide-react';
import type { SelectedElementInfo } from '../../CanvasEditor';

interface ChatComposerProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  executionMode?: 'agent' | 'chat';
  selectedElement?: SelectedElementInfo | null;
  onClearSelectedElement?: () => void;
}

/** Caixa de instrução com indicador de alvo cirúrgico. */
export const ChatComposer: React.FC<ChatComposerProps> = ({
  prompt,
  onPromptChange,
  onSubmit,
  loading,
  selectedElement,
  onClearSelectedElement,
}) => {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="p-3 border-t border-white/[0.08] bg-[#11131b] space-y-2 shrink-0"
    >
      {selectedElement && (
        <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-[11px] text-indigo-300 animate-in fade-in">
          <div className="flex items-center gap-1.5 truncate">
            <Target size={13} className="text-mockbird-cyan shrink-0" />
            <span className="font-semibold text-white">&lt;{selectedElement.tag}&gt;</span>
            <span className="font-mono text-slate-300 truncate">
              {selectedElement.selector || (selectedElement.mbId ? `#${selectedElement.mbId}` : '')}
            </span>
            {selectedElement.snippet && (
              <span className="text-slate-400 truncate italic">“{selectedElement.snippet}”</span>
            )}
          </div>
          {onClearSelectedElement && (
            <button
              type="button"
              onClick={onClearSelectedElement}
              className="p-0.5 rounded hover:bg-indigo-500/20 text-slate-400 hover:text-white transition shrink-0 ml-1"
              title="Desmarcar elemento (voltar para a tela inteira)"
            >
              <X size={12} />
            </button>
          )}
        </div>
      )}

      <textarea
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder={
          selectedElement
            ? `Descreva o que alterar no elemento <${selectedElement.tag}> (ex: trocar texto, mudar cor)...`
             : 'Descreva o que você precisa. O agente analisa a intenção e escolhe o fluxo automaticamente...'
        }
        rows={3}
        disabled={loading}
        className="w-full bg-[#090b10] border border-white/[0.1] focus:border-cyan-400/60 rounded-xl p-3 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none transition leading-relaxed disabled:opacity-60"
      />

      <button
        type="submit"
        disabled={loading || !prompt.trim()}
        className="w-full py-2.5 bg-[#5865dc] hover:bg-[#6975ed] disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition-all"
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-mockbird-cyan" />
             <span>Agente analisando e executando...</span>
          </>
        ) : selectedElement ? (
          <>
            <Target size={14} className="text-mockbird-cyan" />
            <span>Modificar Elemento Selecionado</span>
          </>
        ) : (
          <>
            <Workflow size={14} />
            <span>Executar automaticamente</span>
          </>
        )}
      </button>
    </form>
  );
};
