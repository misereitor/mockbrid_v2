import React, { useState, useEffect } from 'react';
import { MessageSquare, Plus, CheckCircle2, Sparkles, Clock, Check } from 'lucide-react';

interface CommentItem {
  id: string;
  screen_id: string;
  author_name: string;
  element_mb_id: string;
  element_snippet: string;
  pin_x: number;
  pin_y: number;
  body: string;
  status: 'open' | 'resolved';
  created_at: string;
}

interface CommentsPanelProps {
  screenId: string;
  onSendToAI: (commentText: string) => void;
  initialElementContext?: { selector: string; snippet?: string } | null;
}

export const CommentsPanel: React.FC<CommentsPanelProps> = ({ 
  screenId, 
  onSendToAI,
  initialElementContext 
}) => {
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [newCommentBody, setNewCommentBody] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadComments = async () => {
    if (!screenId || screenId === 'temp') return;
    try {
      const res = await fetch(`/api/comments/screen/${screenId}`);
      if (res.ok) {
        const data = await res.json();
        setComments(data);
      }
    } catch (e) {
      console.error('Erro ao buscar comentários:', e);
    }
  };

  useEffect(() => {
    loadComments();
  }, [screenId]);

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCommentBody.trim() || submitting) return;
    setSubmitting(true);
    try {
      const targetMbId = initialElementContext?.selector || 'canvas-element';
      const targetSnippet = initialElementContext?.snippet || '';

      const res = await fetch('/api/comments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          screen_id: screenId,
          element_mb_id: targetMbId,
          element_snippet: targetSnippet,
          pin_x: 50.0,
          pin_y: 50.0,
          body: newCommentBody.trim()
        })
      });
      if (res.ok) {
        setNewCommentBody('');
        loadComments();
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResolve = async (commentId: string) => {
    try {
      const res = await fetch(`/api/comments/${commentId}/resolve`, { method: 'PATCH' });
      if (res.ok) {
        setComments(prev => prev.map(c => c.id === commentId ? { ...c, status: 'resolved' } : c));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const openCount = comments.filter(c => c.status === 'open').length;

  return (
    <div className="flex-1 flex flex-col h-full p-4 space-y-4 select-none overflow-hidden">
      
      {/* Header com contagem */}
      <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
        <span className="text-[11px] font-medium text-slate-400">Apontamentos na tela</span>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-mockbird-blue/15 text-mockbird-cyan border border-mockbird-blue/20 font-medium">
          {openCount} {openCount === 1 ? 'pendente' : 'pendentes'}
        </span>
      </div>

      {/* Alerta de elemento selecionado para comentar */}
      {initialElementContext?.selector && (
        <div className="p-2 rounded-lg bg-mockbird-card border border-mockbird-border text-[11px] text-slate-300 flex items-center justify-between">
          <div className="truncate">
            <span className="text-slate-500">Alvo: </span>
            <span className="font-mono text-mockbird-cyan">{initialElementContext.selector}</span>
          </div>
        </div>
      )}

      {/* Input de Novo Comentário */}
      <form onSubmit={handleAddComment} className="space-y-2 shrink-0">
        <textarea
          rows={2}
          value={newCommentBody}
          onChange={(e) => setNewCommentBody(e.target.value)}
          placeholder="Descreva a alteração desejada ou bug..."
          className="mb-input !text-xs !py-2 resize-none"
        />
        <button
          type="submit"
          disabled={submitting || !newCommentBody.trim()}
          className="mb-btn-primary w-full !py-1.5 !text-xs"
        >
          <Plus size={13} />
          <span>{submitting ? 'Adicionando…' : 'Adicionar apontamento'}</span>
        </button>
      </form>

      {/* Lista de Comentários */}
      <div className="space-y-2.5 flex-1 overflow-y-auto pr-1">
        {comments.length === 0 ? (
          <div className="py-12 text-center text-slate-500 text-xs space-y-1">
            <MessageSquare size={24} className="mx-auto text-slate-600 stroke-1" />
            <p>Nenhum comentário nesta tela.</p>
            <p className="text-[10px] text-slate-600">Clique com botão direito em qualquer elemento para comentar.</p>
          </div>
        ) : (
          comments.map((c) => {
            const isResolved = c.status === 'resolved';
            return (
              <div
                key={c.id}
                className={`p-3 rounded-lg border text-xs space-y-2 transition-all ${
                  isResolved
                    ? 'bg-mockbird-bg/60 border-mockbird-border/40 opacity-50'
                    : 'bg-mockbird-card border-mockbird-border hover:border-mockbird-borderlight shadow-sm'
                }`}
              >
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-medium text-slate-200 flex items-center gap-1.5">
                    <span className="w-4 h-4 rounded-full bg-slate-700 text-white flex items-center justify-center text-[9px] font-semibold">
                      {c.author_name[0]?.toUpperCase() || 'U'}
                    </span>
                    {c.author_name}
                  </span>
                  <span className="text-[10px] text-slate-500 flex items-center gap-1 font-mono">
                    <Clock size={10} />
                    {new Date(c.created_at).toLocaleDateString('pt-BR')}
                  </span>
                </div>

                <p className="text-slate-300 leading-relaxed text-xs">{c.body}</p>

                <div className="flex items-center justify-between pt-2 border-t border-mockbird-border/60">
                  <button
                    onClick={() => onSendToAI(`Corrija na tela o seguinte apontamento: "${c.body}"`)}
                    className="text-[11px] text-mockbird-cyan hover:underline font-medium flex items-center gap-1"
                    title="Pedir para a IA ajustar na tela com 1 clique"
                  >
                    <Sparkles size={11} />
                    <span>Corrigir com IA</span>
                  </button>

                  {!isResolved ? (
                    <button
                      onClick={() => handleResolve(c.id)}
                      className="text-[11px] text-slate-400 hover:text-emerald-400 font-medium flex items-center gap-1 transition-colors"
                    >
                      <Check size={12} />
                      <span>Resolver</span>
                    </button>
                  ) : (
                    <span className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
                      <CheckCircle2 size={11} /> Resolvido
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
