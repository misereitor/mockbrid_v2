import React from 'react';
import { FileCode, GitCompare, Copy, Check } from 'lucide-react';
import type { ChatMessage, DiffLine } from '../../lib/chat';

interface DiffViewerProps {
  message: ChatMessage;
  diffLines: DiffLine[];
  addedCount: number;
  removedCount: number;
  isOpen: boolean;
  tab: 'unified' | 'split';
  onTabChange: (tab: 'unified' | 'split') => void;
  onToggle: () => void;
  onCopy: (id: string, text: string) => void;
  copiedId: string | null;
}

/**
 * Controles e corpo do diff de uma mensagem do assistente.
 * O título do card fica no componente pai.
 */
export const DiffViewer: React.FC<DiffViewerProps> = ({
  message,
  diffLines,
  addedCount,
  removedCount,
  isOpen,
  tab,
  onTabChange,
  onToggle,
  onCopy,
  copiedId,
}) => {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500 font-mono">
          +{addedCount} / -{removedCount}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggle}
            className={`text-[11px] px-2 py-0.5 rounded-md border flex items-center gap-1 font-semibold transition ${
              isOpen
                ? 'bg-mockbird-blue/20 border-mockbird-blue text-white'
                : 'bg-[#0a0a0c] border-mockbird-border text-slate-300 hover:text-white'
            }`}
            title="Ver alterações em formato diff"
          >
            <GitCompare size={12} className={isOpen ? 'text-mockbird-cyan' : 'text-slate-400'} />
            <span>{isOpen ? 'Fechar Diff' : 'Ver Alterações'}</span>
          </button>

          <button
            type="button"
            onClick={() => onCopy(message.id, message.patch || '')}
            className="text-[11px] text-mockbird-cyan hover:underline flex items-center gap-1 font-semibold"
            title="Copiar HTML"
          >
            {copiedId === message.id ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            <span>{copiedId === message.id ? 'Copiado!' : 'Copiar'}</span>
          </button>
        </div>
      </div>

      {isOpen ? (
        <div className="rounded-xl border border-mockbird-border bg-[#08080a] overflow-hidden space-y-1.5 animate-in fade-in duration-150">
          <div className="px-3 py-1.5 bg-[#0e0e12] border-b border-mockbird-border/60 flex items-center justify-between text-[10px]">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <FileCode size={12} className="text-mockbird-cyan" />
                Comparação de Código
              </span>
              <span className="text-emerald-400 font-mono">+{addedCount} adicionadas</span>
              <span className="text-rose-400 font-mono">-{removedCount} removidas</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onTabChange('unified')}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition ${
                  tab === 'unified' ? 'bg-mockbird-blue text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                Diff Colorido
              </button>
              <button
                type="button"
                onClick={() => onTabChange('split')}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition ${
                  tab === 'split' ? 'bg-mockbird-blue text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                Antes vs Depois
              </button>
            </div>
          </div>

          {tab === 'unified' ? (
            <div className="p-2 font-mono text-[10px] max-h-48 overflow-y-auto space-y-0.5 select-text">
              {diffLines.map((d, i) => (
                <div
                  key={i}
                  className={`px-1.5 py-0.5 rounded flex items-start gap-2 leading-tight ${
                    d.type === 'added'
                      ? 'bg-emerald-950/40 text-emerald-300 border-l-2 border-emerald-500'
                      : d.type === 'removed'
                      ? 'bg-rose-950/40 text-rose-300 border-l-2 border-rose-500'
                      : 'text-slate-400'
                  }`}
                >
                  <span className="font-bold select-none w-3 text-center shrink-0">
                    {d.type === 'added' ? '+' : d.type === 'removed' ? '-' : ' '}
                  </span>
                  <span className="whitespace-pre-wrap break-all">{d.text}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-1 p-2 font-mono text-[9px] max-h-48 overflow-y-auto">
              <div className="p-2 rounded bg-rose-950/20 border border-rose-500/20 text-rose-200 space-y-1">
                <span className="text-[10px] font-bold text-rose-400 block pb-1 border-b border-rose-500/20">Original (Antes)</span>
                <pre className="whitespace-pre-wrap break-all select-text">
                  {message.patchType === 'element'
                    ? message.elementSnapshotBefore || '(sem snapshot)'
                    : message.htmlSnapshotBefore?.slice(0, 400) || '(sem snapshot)'}
                </pre>
              </div>
              <div className="p-2 rounded bg-emerald-950/20 border border-emerald-500/20 text-emerald-200 space-y-1">
                <span className="text-[10px] font-bold text-emerald-400 block pb-1 border-b border-emerald-500/20">Novo (Depois)</span>
                <pre className="whitespace-pre-wrap break-all select-text">
                  {(message.patch || '').slice(0, 400)}...
                </pre>
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Preview Compacto */
        <div className="p-2 rounded-lg bg-[#0a0a0c] border border-mockbird-border/60 text-[10px] font-mono text-slate-400 max-h-24 overflow-y-auto whitespace-pre-wrap select-text">
          {(message.patch || '').slice(0, 260)}...
        </div>
      )}
    </div>
  );
};
