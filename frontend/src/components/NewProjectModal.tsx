import React, { useState } from 'react';
import { FolderPlus, Sparkles, X, ArrowRight, History } from 'lucide-react';

interface NewProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreateProject: (name: string, description: string) => Promise<void>;
  recentProject?: { id: string; name: string } | null;
  onContinueRecent?: (id: string) => void;
}

export const NewProjectModal: React.FC<NewProjectModalProps> = ({
  isOpen,
  onClose,
  onCreateProject,
  recentProject,
  onContinueRecent,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalName = name.trim() || 'Novo Projeto';
    setCreating(true);
    try {
      await onCreateProject(finalName, description.trim());
      setName('');
      setDescription('');
      onClose();
    } catch (err: any) {
      alert(err.message || 'Erro ao criar projeto');
    } finally {
      setCreating(false);
    }
  };

  const handleQuickBlank = async () => {
    setCreating(true);
    try {
      await onCreateProject('Novo Projeto', 'Criado via atalho rápido do editor');
      onClose();
    } catch (err: any) {
      alert(err.message || 'Erro ao criar projeto');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-150">
      <div 
        className="w-full max-w-lg bg-mockbird-card border border-mockbird-border rounded-2xl p-6 shadow-2xl space-y-5 animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        {/* Cabeçalho */}
        <div className="flex items-center justify-between border-b border-mockbird-border pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-mockbird-cyan/10 border border-mockbird-cyan/20 flex items-center justify-center text-mockbird-cyan">
              <FolderPlus size={20} />
            </div>
            <div>
              <h2 id="modal-title" className="text-base font-bold text-white flex items-center gap-2">
                Iniciar no Editor
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Crie um novo projeto limpo para editar ou continue o anterior.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-mockbird-surface transition-colors"
            title="Fechar"
            aria-label="Fechar"
          >
            <X size={16} />
          </button>
        </div>

        {/* Formulário Novo Projeto */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Nome do Projeto <span className="text-slate-500">(opcional)</span>
            </label>
            <input
              type="text"
              autoFocus
              placeholder="Ex: Landing Page SaaS, App Mobile, Dashboard..."
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mb-input w-full !text-sm"
              disabled={creating}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Descrição <span className="text-slate-500">(opcional)</span>
            </label>
            <textarea
              rows={2}
              placeholder="Breve resumo dos objetivos deste protótipo..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mb-input w-full !text-xs resize-none"
              disabled={creating}
            />
          </div>

          <div className="flex flex-col sm:flex-row gap-2.5 pt-2">
            <button
              type="submit"
              disabled={creating}
              className="mb-btn-primary flex-1 justify-center !py-2.5 !text-xs font-semibold gap-2 shadow-lg shadow-mockbird-blue/20"
            >
              <Sparkles size={14} />
              {creating ? 'Criando Projeto…' : 'Criar e Começar a Editar'}
            </button>

            <button
              type="button"
              disabled={creating}
              onClick={handleQuickBlank}
              className="mb-btn-outline justify-center !py-2.5 !text-xs font-medium"
              title="Cria rapidamente um projeto com nome 'Novo Projeto'"
            >
              Criar em Branco
            </button>
          </div>
        </form>

        {/* Opção para continuar projeto recente se existir */}
        {recentProject && onContinueRecent && (
          <div className="pt-4 border-t border-mockbird-border/70">
            <div className="text-[11px] font-medium text-slate-400 mb-2 flex items-center gap-1.5">
              <History size={13} className="text-slate-500" />
              <span>Ou continuar trabalhando no projeto recente:</span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-xl bg-mockbird-surface border border-mockbird-border/80 hover:border-mockbird-border transition-colors">
              <div className="min-w-0 pr-2">
                <div className="text-xs font-semibold text-slate-200 truncate">
                  {recentProject.name}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  Último projeto acessado
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  onContinueRecent(recentProject.id);
                  onClose();
                }}
                className="mb-btn-outline !py-1.5 !px-3 !text-xs shrink-0 flex items-center gap-1.5 text-mockbird-cyan hover:bg-mockbird-cyan/10"
              >
                <span>Continuar</span>
                <ArrowRight size={13} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
