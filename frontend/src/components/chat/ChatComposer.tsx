import React, { useRef } from 'react';
import { ArrowUp, ChevronDown, Cpu, ImagePlus, Loader2, Target, X } from 'lucide-react';
import type { SelectedElementInfo } from '../../CanvasEditor';

interface ChatComposerProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  executionMode?: 'agent' | 'chat';
  selectedElement?: SelectedElementInfo | null;
  onClearSelectedElement?: () => void;
  availableModels?: string[];
  selectedModel?: string;
  onSelectModel?: (model: string) => void;
  attachedImage?: string | null;
  onAttachedImageChange?: (image: string | null) => void;
}

/** Composer unificado estilo IDE moderna com seletor de modelo integrado, anexo de imagens e indicador de alvo cirúrgico. */
export const ChatComposer: React.FC<ChatComposerProps> = ({
  prompt,
  onPromptChange,
  onSubmit,
  loading,
  selectedElement,
  onClearSelectedElement,
  availableModels = [],
  selectedModel = '',
  onSelectModel,
  attachedImage,
  onAttachedImageChange,
}) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const canSend = !loading && Boolean(prompt.trim() || attachedImage);

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            const result = ev.target?.result as string;
            if (result && onAttachedImageChange) onAttachedImageChange(result);
          };
          reader.readAsDataURL(file);
          e.preventDefault();
          break;
        }
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (ev) => {
        const result = ev.target?.result as string;
        if (result && onAttachedImageChange) onAttachedImageChange(result);
      };
      reader.readAsDataURL(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className="px-3 pt-2 pb-2.5 bg-[#0b0d13] shrink-0"
    >
      <div
        className={`rounded-2xl bg-[#12151f] border transition-all duration-200 overflow-hidden shadow-lg ${
          selectedElement
            ? 'border-cyan-400/40 focus-within:border-cyan-400/70 shadow-cyan-950/20'
            : 'border-white/[0.08] focus-within:border-cyan-400/40 focus-within:shadow-[0_0_24px_-6px_rgba(34,211,238,0.2)]'
        }`}
      >
        {/* Banner de Elemento Selecionado no Canvas (Edição Cirúrgica) */}
        {selectedElement && (
          <div className="flex items-center justify-between px-3 py-1.5 bg-gradient-to-r from-cyan-500/15 via-indigo-500/10 to-transparent border-b border-cyan-400/20 text-[11px] animate-in fade-in">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="flex h-4 w-4 items-center justify-center rounded bg-cyan-400/20 text-cyan-300 shrink-0">
                <Target size={11} />
              </span>
              <span className="font-mono font-semibold text-cyan-300 shrink-0">
                &lt;{selectedElement.tag}&gt;
              </span>
              <span className="font-mono text-[10px] text-slate-300 truncate">
                {selectedElement.selector || (selectedElement.mbId ? `#${selectedElement.mbId}` : '')}
              </span>
              {selectedElement.snippet && (
                <span className="text-[10px] text-slate-400 truncate italic hidden sm:inline">
                  “{selectedElement.snippet}”
                </span>
              )}
            </div>
            {onClearSelectedElement && (
              <button
                type="button"
                onClick={onClearSelectedElement}
                className="p-0.5 rounded-md hover:bg-white/10 text-slate-400 hover:text-white transition shrink-0 ml-1.5"
                title="Desmarcar elemento (editar tela inteira)"
              >
                <X size={12} />
              </button>
            )}
          </div>
        )}

        {/* Banner de Imagem Anexada */}
        {attachedImage && (
          <div className="flex items-center gap-2.5 px-3 py-1.5 bg-gradient-to-r from-cyan-500/10 via-slate-800/40 to-transparent border-b border-white/[0.06] text-[11px] animate-in fade-in">
            <div className="relative rounded overflow-hidden w-7 h-7 border border-cyan-400/30 shrink-0 shadow-sm">
              <img src={attachedImage} alt="Referência visual" className="w-full h-full object-cover" />
            </div>
            <span className="text-[11px] text-slate-300 truncate">Referência visual anexada</span>
            {onAttachedImageChange && (
              <button
                type="button"
                onClick={() => onAttachedImageChange(null)}
                className="ml-auto p-1 rounded-md hover:bg-white/10 text-slate-400 hover:text-white transition shrink-0"
                title="Remover anexo"
              >
                <X size={12} />
              </button>
            )}
          </div>
        )}

        {/* Área de texto */}
        <textarea
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          onPaste={handlePaste}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (canSend) onSubmit();
            }
          }}
          placeholder={
            selectedElement
              ? `O que deseja alterar em <${selectedElement.tag}>? (ex: mudar cor, texto, espaçamento)...`
              : 'Peça uma nova seção, ajuste de layout ou melhoria visual...'
          }
          rows={3}
          disabled={loading}
          className="w-full bg-transparent px-3.5 pt-3 pb-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none leading-relaxed disabled:opacity-60"
        />

        {/* Barra inferior do Composer: Seletor de Modelo + Botão de Envio */}
        <div className="px-3 pb-2.5 pt-1 flex items-center justify-between gap-2">
          <div className="flex items-center min-w-0">
            {availableModels.length > 0 && onSelectModel ? (
              <div className="relative inline-flex items-center rounded-lg bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] px-2.5 h-7 transition max-w-[220px]">
                <Cpu size={12} className="text-cyan-400 shrink-0 mr-1.5" />
                <select
                  value={selectedModel}
                  onChange={(e) => onSelectModel(e.target.value)}
                  disabled={loading}
                  aria-label="Selecionar modelo de IA"
                  className="appearance-none bg-transparent border-0 text-[11px] font-mono text-slate-300 hover:text-white focus:outline-none cursor-pointer truncate pr-4 max-w-[175px]"
                >
                  {availableModels.map((m) => (
                    <option key={m} value={m} className="bg-[#12151f] text-slate-200">
                      {m}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  size={12}
                  className="pointer-events-none absolute right-2 text-slate-500"
                />
              </div>
            ) : null}

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              className={`h-7 w-7 rounded-lg flex items-center justify-center transition ml-1.5 ${
                attachedImage
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/40'
                  : 'bg-white/[0.03] hover:bg-white/[0.08] text-slate-400 hover:text-slate-200 border border-white/[0.06]'
              }`}
              title="Anexar print ou referência visual (ou use Ctrl+V)"
              aria-label="Anexar imagem de referência"
            >
              <ImagePlus size={13} />
            </button>
          </div>

          <button
            type="submit"
            disabled={!canSend}
            aria-label={selectedElement ? 'Aplicar no elemento selecionado' : 'Enviar'}
            title={selectedElement ? 'Modificar elemento selecionado' : 'Enviar instrução'}
            className={`h-7 w-7 rounded-lg flex items-center justify-center shrink-0 transition-all ${
              loading
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/30 cursor-wait'
                : canSend
                ? 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 shadow-sm shadow-cyan-500/25'
                : 'bg-white/[0.06] text-slate-500 cursor-not-allowed'
            }`}
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin text-cyan-300" />
            ) : (
              <ArrowUp size={15} strokeWidth={2.5} />
            )}
          </button>
        </div>
      </div>
    </form>
  );
};
