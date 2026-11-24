import React, { useState, useEffect } from 'react';
import { Database, Plus, Check, Trash2 } from 'lucide-react';

export interface Scenario {
  id?: string;
  name: string;
  data: Record<string, any>;
}

interface ScenariosManagerProps {
  projectId?: string;
  scenarios?: Scenario[];
  activeScenarioName?: string;
  onSelectScenario?: (name: string) => void;
  onAddScenario?: (scenario: Scenario) => void;
  onApplyScenario?: (data: Record<string, any>) => void;
}

export function ScenariosManager({
  projectId,
  scenarios: initialScenarios,
  activeScenarioName: initialActive,
  onSelectScenario,
  onAddScenario,
  onApplyScenario
}: ScenariosManagerProps) {
  const [scenarios, setScenarios] = useState<Scenario[]>(initialScenarios || [
    { name: 'Cenário Sucesso', data: { status: 'sucesso', itens: [{ id: 1, nome: 'Exemplo' }] } },
    { name: 'Cenário Vazio', data: { status: 'vazio', itens: [] } },
    { name: 'Cenário Erro', data: { status: 'erro', mensagem: 'Falha no processamento' } }
  ]);
  const [activeName, setActiveName] = useState(initialActive || 'Cenário Sucesso');
  const [showModal, setShowModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newJson, setNewJson] = useState('{\n  "status": "sucesso",\n  "itens": []\n}');

  useEffect(() => {
    if (projectId) {
      fetch(`/api/projects/${projectId}/scenarios`)
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setScenarios(data);
            setActiveName(data[0].name);
            if (onApplyScenario) onApplyScenario(data[0].data);
          }
        })
        .catch(() => {});
    }
  }, [projectId]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const parsed = JSON.parse(newJson);
      const cleanName = newName.trim();
      let createdScenario: Scenario = { name: cleanName, data: parsed };

      if (projectId) {
        try {
          const res = await fetch(`/api/projects/${projectId}/scenarios`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: cleanName, data: parsed }),
          });
          if (res.ok) {
            createdScenario = await res.json();
          }
        } catch (err) {
          console.error('Erro ao salvar cenário no servidor:', err);
        }
      }

      setScenarios(prev => [...prev, createdScenario]);
      setActiveName(createdScenario.name);
      if (onAddScenario) onAddScenario(createdScenario);
      if (onApplyScenario) onApplyScenario(parsed);
      setShowModal(false);
      setNewName('');
    } catch {
      alert('JSON Inválido! Corrija a sintaxe antes de salvar.');
    }
  };

  const handleDelete = async (sc: Scenario, e: React.MouseEvent) => {
    e.stopPropagation();
    if (scenarios.length <= 1) return;
    if (sc.id && projectId) {
      try {
        await fetch(`/api/projects/${projectId}/scenarios/${sc.id}`, { method: 'DELETE' });
      } catch (err) {
        console.error('Erro ao excluir cenário:', err);
      }
    }
    const filtered = scenarios.filter(s => (s.id ? s.id !== sc.id : s.name !== sc.name));
    setScenarios(filtered);
    if (activeName === sc.name && filtered.length > 0) {
      handleSelect(filtered[0]);
    }
  };

  const handleSelect = (s: Scenario) => {
    setActiveName(s.name);
    if (onSelectScenario) onSelectScenario(s.name);
    if (onApplyScenario) onApplyScenario(s.data);
  };

  return (
    <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full p-4 space-y-4 shrink-0 select-none">
      <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
        <h3 className="font-bold text-xs uppercase tracking-wider flex items-center gap-2 text-white">
          <Database className="h-4 w-4 text-mockbird-cyan" />
          Cenários de Mock
        </h3>
        <button 
          onClick={() => setShowModal(true)}
          className="p-1 rounded-lg bg-mockbird-blue hover:bg-mockbird-bluedark text-white text-xs transition"
          title="Novo Cenário"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <p className="text-xs text-slate-400">
        Alterne entre estados de dados para testar sua interface com sucesso, erro ou lista vazia.
      </p>

      {/* Lista de Cenários */}
      <div className="space-y-2 flex-1 overflow-y-auto">
        {scenarios.map((s) => {
          const isActive = activeName === s.name;
          return (
            <div 
              key={s.id || s.name}
              onClick={() => handleSelect(s)}
              className={`p-3 rounded-xl border cursor-pointer transition text-xs group ${
                isActive 
                  ? 'bg-mockbird-blue/15 border-mockbird-cyan text-white shadow-sm ring-1 ring-mockbird-cyan/40' 
                  : 'bg-mockbird-card border-mockbird-border text-slate-300 hover:border-slate-500'
              }`}
            >
              <div className="flex items-center justify-between font-semibold">
                <span>{s.name}</span>
                <div className="flex items-center gap-1.5">
                  {isActive && <Check className="h-3.5 w-3.5 text-mockbird-cyan" />}
                  {scenarios.length > 1 && (
                    <button
                      type="button"
                      onClick={(e) => handleDelete(s, e)}
                      className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-slate-500 hover:text-rose-400 transition"
                      title="Excluir cenário"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
              <pre className="mt-1.5 text-[10px] font-mono text-slate-400 bg-mockbird-surface p-2 rounded-lg border border-mockbird-border/60 overflow-hidden line-clamp-3">
                {JSON.stringify(s.data, null, 2)}
              </pre>
            </div>
          );
        })}
      </div>

      {/* Modal / Formulário de Criação */}
      {showModal && (
        <div className="p-4 bg-mockbird-card border border-mockbird-cyan/50 rounded-xl space-y-3 animate-in fade-in">
          <span className="text-xs font-bold text-white uppercase tracking-wider">Criar Novo Cenário</span>
          <form onSubmit={handleCreate} className="space-y-2.5">
            <input 
              type="text"
              required
              placeholder="Nome (ex.: Sucesso Pagamento)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full px-3 py-1.5 text-xs rounded-lg bg-mockbird-surface border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
            />
            <textarea 
              rows={4}
              value={newJson}
              onChange={(e) => setNewJson(e.target.value)}
              className="w-full p-2 text-[11px] font-mono rounded-lg bg-mockbird-surface border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan resize-none"
            />
            <div className="flex gap-2">
              <button 
                type="submit"
                className="flex-1 py-1.5 bg-mockbird-blue text-white rounded-lg text-xs font-semibold"
              >
                Salvar
              </button>
              <button 
                type="button"
                onClick={() => setShowModal(false)}
                className="px-3 py-1.5 bg-mockbird-surface text-slate-400 hover:text-white rounded-lg text-xs"
              >
                Cancelar
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
