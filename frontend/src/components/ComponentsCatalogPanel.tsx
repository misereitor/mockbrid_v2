import React, { useState } from 'react';
import { Layers, Plus, Check } from 'lucide-react';
import { BASE_COMPONENTS, ComponentTemplate } from '../catalog';

interface ComponentsCatalogPanelProps {
  onInsertComponent: (html: string) => void;
}

export const ComponentsCatalogPanel: React.FC<ComponentsCatalogPanelProps> = ({ onInsertComponent }) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('Todos');
  const [insertedId, setInsertedId] = useState<string | null>(null);

  const categories = ['Todos', 'SaaS', 'Layout', 'Actions', 'Forms', 'Feedback', 'Navigation'];

  const filtered = selectedCategory === 'Todos'
    ? BASE_COMPONENTS
    : BASE_COMPONENTS.filter(c => c.category === selectedCategory);

  const handleInsert = (comp: ComponentTemplate) => {
    onInsertComponent(comp.defaultHtml);
    setInsertedId(comp.id);
    setTimeout(() => setInsertedId(null), 2000);
  };

  return (
    <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full p-4 space-y-4 shrink-0 select-none">
      
      <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
        <h3 className="font-bold text-xs uppercase tracking-wider flex items-center gap-2 text-white">
          <Layers className="h-4 w-4 text-mockbird-cyan" />
          Blocos & Componentes
        </h3>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-mockbird-blue/10 text-mockbird-cyan border border-mockbird-blue/20 font-bold">
          {BASE_COMPONENTS.length} Prontos
        </span>
      </div>

      {/* Category Pills */}
      <div className="flex flex-wrap gap-1">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-all ${
              selectedCategory === cat
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'bg-mockbird-card text-slate-400 hover:text-white border border-mockbird-border/60'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      <p className="text-xs text-slate-400">
        Clique em "Inserir" para adicionar o bloco diretamente no layout da tela ativa respeitando os tokens do projeto.
      </p>

      {/* Components List */}
      <div className="space-y-3 flex-1 overflow-y-auto">
        {filtered.map((comp) => {
          const isInserted = insertedId === comp.id;
          return (
            <div
              key={comp.id}
              className="bg-mockbird-card border border-mockbird-border hover:border-mockbird-cyan/50 p-3.5 rounded-xl space-y-2 transition-all group"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-xs text-white group-hover:text-mockbird-cyan transition-colors">
                  {comp.name}
                </span>
                <span className="text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded bg-mockbird-surface border border-mockbird-border text-slate-400">
                  {comp.category}
                </span>
              </div>

              <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                {comp.description}
              </p>

              <button
                onClick={() => handleInsert(comp)}
                className={`w-full py-1.5 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all shadow-sm ${
                  isInserted
                    ? 'bg-emerald-600 text-white'
                    : 'bg-mockbird-surface hover:bg-mockbird-blue text-slate-200 hover:text-white border border-mockbird-border hover:border-mockbird-blue'
                }`}
              >
                {isInserted ? (
                  <>
                    <Check size={13} />
                    <span>Inserido na Tela!</span>
                  </>
                ) : (
                  <>
                    <Plus size={13} />
                    <span>Inserir na Tela</span>
                  </>
                )}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

