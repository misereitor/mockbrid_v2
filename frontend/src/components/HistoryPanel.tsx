import React, { useState, useEffect } from 'react';
import { History, RotateCcw, Clock, User, AlertCircle, X } from 'lucide-react';

interface Revision {
  id: string;
  screen_id: string;
  revision_number: number;
  actor: string;
  change_summary: string;
  created_at: string;
  html_content: string;
  css_content: string;
  js_content: string;
}

interface HistoryPanelProps {
  screenId: string;
  onRevertSuccess: (revertedScreen: any) => void;
  onClose?: () => void;
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({ screenId, onRevertSuccess, onClose }) => {
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(false);
  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchRevisions = async () => {
    if (!screenId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/screens/${screenId}/revisions`);
      if (!res.ok) throw new Error('Não foi possível carregar as revisões');
      const data = await res.json();
      setRevisions(data);
    } catch (e: any) {
      setError(e.message || 'Erro ao carregar histórico');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRevisions();
  }, [screenId]);

  const handleRevert = async (revId: string, revNum: number) => {
    if (!confirm(`Deseja realmente reverter para a revisão #${revNum}? Uma nova revisão de checkpoint será criada.`)) {
      return;
    }
    setRevertingId(revId);
    try {
      const res = await fetch(`/api/screens/${screenId}/revisions/${revId}/revert`, {
        method: 'POST'
      });
      if (!res.ok) throw new Error('Falha ao reverter revisão');
      const updatedScreen = await res.json();
      onRevertSuccess(updatedScreen);
      fetchRevisions();
    } catch (e: any) {
      alert(e.message || 'Erro ao reverter');
    } finally {
      setRevertingId(null);
    }
  };

  return (
    <div className="flex flex-col h-full bg-mockbird-surface text-slate-200">
      <div className="p-4 border-b border-mockbird-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History size={16} className="text-mockbird-cyan" />
          <h3 className="text-sm font-semibold">Histórico de Versões</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400 font-mono">
            {revisions.length} checkpoints
          </span>
          {onClose && (
            <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded" title="Fechar">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {loading && revisions.length === 0 && (
          <div className="text-center py-8 text-xs text-slate-400">
            Carregando histórico...
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle size={14} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!loading && revisions.length === 0 && !error && (
          <div className="text-center py-10 text-xs text-slate-500">
            Nenhuma revisão registrada ainda. Altere a tela para criar checkpoints automáticos.
          </div>
        )}

        {revisions.map((rev, index) => {
          const isLatest = index === 0;
          const dateStr = new Date(rev.created_at).toLocaleString('pt-BR', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
          });

          return (
            <div
              key={rev.id}
              className={`p-3 rounded-xl border transition-all ${
                isLatest
                  ? 'bg-mockbird-card/80 border-mockbird-cyan/40 shadow-sm'
                  : 'bg-mockbird-bg border-mockbird-border hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-bold text-white flex items-center gap-1.5">
                  #{rev.revision_number}
                  {isLatest && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-mockbird-cyan/20 text-mockbird-cyan font-normal">
                      Atual
                    </span>
                  )}
                </span>
                <span className="text-[10px] text-slate-400 flex items-center gap-1">
                  <Clock size={11} /> {dateStr}
                </span>
              </div>

              <p className="text-xs text-slate-300 mb-2 font-sans line-clamp-2">
                {rev.change_summary || 'Atualização visual ou de código'}
              </p>

              <div className="flex items-center justify-between pt-2 border-t border-mockbird-border/50 text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <User size={11} /> {rev.actor || 'Usuário'}
                </span>

                {!isLatest && (
                  <button
                    onClick={() => handleRevert(rev.id, rev.revision_number)}
                    disabled={revertingId === rev.id}
                    className="px-2 py-1 rounded-md bg-mockbird-blue/20 hover:bg-mockbird-blue text-mockbird-blue hover:text-white font-medium text-[11px] flex items-center gap-1 transition"
                  >
                    <RotateCcw size={11} />
                    <span>{revertingId === rev.id ? 'Revertendo...' : 'Reverter'}</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
