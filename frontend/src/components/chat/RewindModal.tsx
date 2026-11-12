import React from 'react';
import { RotateCcw } from 'lucide-react';

export interface RewindTarget {
  msgId: string;
  index: number;
  isUser: boolean;
  content: string;
  snapshotHtml: string;
}

interface RewindModalProps {
  target: RewindTarget;
  revertCode: boolean;
  onRevertCodeChange: (value: boolean) => void;
  reloadPrompt: boolean;
  onReloadPromptChange: (value: boolean) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

/** Confirmação de "voltar até esta mensagem" (rollback do histórico). */
export const RewindModal: React.FC<RewindModalProps> = ({
  target,
  revertCode,
  onRevertCodeChange,
  reloadPrompt,
  onReloadPromptChange,
  onCancel,
  onConfirm,
}) => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-150">
      <div className="bg-mockbird-surface border border-mockbird-border rounded-2xl p-4 max-w-sm w-full space-y-4 shadow-2xl animate-in zoom-in-95 duration-150 text-slate-200">
        <div className="flex items-center gap-2 text-mockbird-cyan font-bold text-xs">
          <RotateCcw size={16} />
          <span>Voltar histórico até esta mensagem?</span>
        </div>

        <p className="text-[11px] text-slate-400 leading-relaxed">
          Você está retrocedendo a conversa. As mensagens enviadas após este ponto serão descartadas do histórico.
        </p>

        <div className="p-2.5 rounded-lg bg-[#0a0a0c] border border-mockbird-border/60 text-[11px] text-slate-300 font-mono line-clamp-3 select-text">
          “{target.content}”
        </div>

        <div className="space-y-2 pt-1 border-t border-mockbird-border/60">
          <label className="flex items-start gap-2.5 text-[11px] text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={revertCode}
              onChange={(e) => onRevertCodeChange(e.target.checked)}
              className="mt-0.5 rounded border-mockbird-border text-mockbird-blue focus:ring-0 cursor-pointer"
            />
            <div>
              <span className="font-semibold text-white block">Reverter também o código da tela</span>
              <span className="text-[10px] text-slate-400">Restaura o Canvas para o estado visual correspondente a este momento</span>
            </div>
          </label>

          {target.isUser && (
            <label className="flex items-start gap-2.5 text-[11px] text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={reloadPrompt}
                onChange={(e) => onReloadPromptChange(e.target.checked)}
                className="mt-0.5 rounded border-mockbird-border text-mockbird-blue focus:ring-0 cursor-pointer"
              />
              <div>
                <span className="font-semibold text-white block">Carregar prompt para edição</span>
                <span className="text-[10px] text-slate-400">Coloca o texto da mensagem na caixa de prompt para reenviar com ajustes</span>
              </div>
            </label>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-mockbird-border/60">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-mockbird-card transition"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-mockbird-blue hover:bg-mockbird-bluedark text-white flex items-center gap-1.5 transition shadow-md"
          >
            <RotateCcw size={13} />
            <span>Confirmar e Voltar</span>
          </button>
        </div>
      </div>
    </div>
  );
};
