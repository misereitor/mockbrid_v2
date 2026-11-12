import React, { useState, useEffect } from 'react';
import { 
  Cpu, 
  Key, 
  Sparkles, 
  Check, 
  Copy, 
  Terminal, 
  ShieldCheck, 
  Plus, 
  Trash2, 
  Star, 
  RefreshCw, 
  AlertCircle, 
  CheckCircle2,
  Globe,
  Sliders,
  Mail
} from 'lucide-react';
import { EmailSettingsPanel } from '../components/EmailSettingsPanel';

interface AIProviderData {
  id?: string;
  provider_type: string;
  default_model: string;
  base_url?: string;
  custom_models?: string[];
  is_active?: boolean;
}

interface SettingsPageProps {
  onNotify?: (msg: string) => void;
  currentUser?: { is_system_admin?: boolean } | null;
}

const PRESET_PROVIDERS = [
  { id: 'openai', name: 'OpenAI', defaultUrl: 'https://api.openai.com/v1', defaultModel: 'gpt-4o-mini' },
  { id: 'openrouter', name: 'OpenRouter (Multi-modelos)', defaultUrl: 'https://openrouter.ai/api/v1', defaultModel: 'deepseek/deepseek-r1' },
  { id: 'anthropic', name: 'Anthropic Claude', defaultUrl: 'https://api.anthropic.com/v1', defaultModel: 'claude-3-7-sonnet-20250219' },
  { id: 'gemini', name: 'Google Gemini (OpenAI compat)', defaultUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', defaultModel: 'gemini-2.0-flash' },
  { id: 'ollama', name: 'Ollama Local / Servidor', defaultUrl: 'http://localhost:11434/v1', defaultModel: 'deepseek-r1:14b' },
  { id: 'custom', name: 'Custom / OpenAI-Compatible (DeepSeek, Groq, Together, vLLM)', defaultUrl: 'https://api.deepseek.com/v1', defaultModel: 'deepseek-chat' },
];

const POPULAR_SUGGESTIONS = [
  { label: 'DeepSeek R1', model: 'deepseek/deepseek-r1' },
  { label: 'Qwen 2.5 Coder 32B', model: 'qwen/qwen-2.5-coder-32b' },
  { label: 'Claude 3.7 Sonnet', model: 'claude-3-7-sonnet-20250219' },
  { label: 'GPT-4o', model: 'gpt-4o' },
  { label: 'GPT-4o Mini', model: 'gpt-4o-mini' },
  { label: 'Llama 3.3 70B', model: 'meta-llama/llama-3.3-70b-instruct' },
  { label: 'Gemini 2.0 Flash', model: 'google/gemini-2.0-flash-001' },
  { label: 'DeepSeek V3', model: 'deepseek/deepseek-chat' },
];

export const SettingsPage: React.FC<SettingsPageProps> = ({ currentUser }) => {
  const [activeTab, setActiveTab] = useState<'ai' | 'mcp' | 'org' | 'email'>('ai');

  // AI Config State
  const [providerType, setProviderType] = useState('openrouter');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1');
  const [defaultModel, setDefaultModel] = useState('deepseek/deepseek-r1');
  const [customModels, setCustomModels] = useState<string[]>([
    'deepseek/deepseek-r1',
    'qwen/qwen-2.5-coder-32b',
    'claude-3-7-sonnet-20250219',
    'gpt-4o-mini',
    'meta-llama/llama-3.3-70b-instruct'
  ]);
  const [newModelInput, setNewModelInput] = useState('');
  
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: 'ok' | 'error'; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState<string | null>(null);

  // Plano de IA da organização
  const [usage, setUsage] = useState<any>(null);
  const [plans, setPlans] = useState<any[]>([]);
  const [userRole, setUserRole] = useState('');
  const [assigningPlan, setAssigningPlan] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then(u => u && setUserRole(u.role))
      .catch(() => {});
    fetch('/api/org/ai-usage')
      .then(r => (r.ok ? r.json() : null))
      .then(setUsage)
      .catch(() => {});
    fetch('/api/ai/plans')
      .then(r => (r.ok ? r.json() : []))
      .then(setPlans)
      .catch(() => {});
  }, []);

  const handleAssignPlan = async (planSlug: string) => {
    setAssigningPlan(planSlug);
    try {
      const res = await fetch('/api/org/plan', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_slug: planSlug }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Falha ao trocar de plano');
      setUsage(data);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setAssigningPlan(null);
    }
  };

  // Carrega configurações existentes
  useEffect(() => {
    fetch('/api/ai/providers')
      .then(r => r.json())
      .then((data: AIProviderData[]) => {
        if (data && data.length > 0) {
          const prov = data[0];
          setProviderType(prov.provider_type);
          setDefaultModel(prov.default_model);
          if (prov.base_url) setBaseUrl(prov.base_url);
          if (prov.custom_models && prov.custom_models.length > 0) {
            setCustomModels(prov.custom_models);
          }
        }
      })
      .catch(err => console.error('Erro ao ler provedores:', err));
  }, []);

  const handleProviderChange = (type: string) => {
    setProviderType(type);
    const preset = PRESET_PROVIDERS.find(p => p.id === type);
    if (preset) {
      setBaseUrl(preset.defaultUrl);
      if (!customModels.includes(preset.defaultModel)) {
        setCustomModels(prev => [preset.defaultModel, ...prev]);
      }
      setDefaultModel(preset.defaultModel);
    }
  };

  const handleAddCustomModel = (modelNameToAdd?: string) => {
    const target = (modelNameToAdd || newModelInput).trim();
    if (!target) return;
    if (!customModels.includes(target)) {
      setCustomModels(prev => [...prev, target]);
    }
    if (!modelNameToAdd) setNewModelInput('');
  };

  const handleRemoveModel = (m: string) => {
    const filtered = customModels.filter(x => x !== m);
    setCustomModels(filtered);
    if (defaultModel === m && filtered.length > 0) {
      setDefaultModel(filtered[0]);
    }
  };

  const handleSetDefaultModel = (m: string) => {
    setDefaultModel(m);
  };

  const handleTestConnection = async () => {
    if (!apiKey.trim() && providerType !== 'ollama') {
      setTestResult({ status: 'error', message: 'Preencha a API Key para realizar o teste de conexão.' });
      return;
    }
    setTesting(true);
    setTestResult(null);

    try {
      const res = await fetch('/api/ai/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: providerType,
          api_key: apiKey.trim(),
          base_url: baseUrl.trim(),
          model_name: defaultModel.trim()
        })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        setTestResult({ status: 'ok', message: data.message });
      } else {
        setTestResult({ status: 'error', message: data.message || 'Falha ao testar conexão.' });
      }
    } catch (e: any) {
      setTestResult({ status: 'error', message: e.message || 'Erro de rede ao testar conexão.' });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveAIConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveSuccess(false);

    try {
      const res = await fetch('/api/ai/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: providerType,
          api_key: apiKey.trim(),
          default_model: defaultModel.trim(),
          base_url: baseUrl.trim(),
          custom_models: customModels
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Falha ao salvar configuração');
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const mcpClaudeConfig = JSON.stringify({
    mcpServers: {
      mockbird_v2: {
        command: "npx",
        args: ["-y", "mcp-proxy", `${window.location.origin}/mcp/sse`]
      }
    }
  }, null, 2);

  const mcpCursorConfig = JSON.stringify({
    "mcp.servers": {
      "mockbird_v2": {
        "url": `${window.location.origin}/mcp/info`
      }
    }
  }, null, 2);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedMcp(id);
    setTimeout(() => setCopiedMcp(null), 2500);
  };

  return (
    <div className="flex-1 max-w-6xl w-full mx-auto px-6 py-8 flex flex-col gap-6">
      
      {/* Header da Página */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-mockbird-border pb-6">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2.5">
            <Sliders size={24} className="text-mockbird-cyan" />
            Configurações & Integrações
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Gerencie provedores de Inteligência Artificial com suporte a qualquer modelo customizado e conecte seu MCP ao Claude ou Cursor.
          </p>
        </div>

        {/* Tab Buttons */}
        <div className="flex bg-mockbird-surface p-1 rounded-xl border border-mockbird-border shrink-0">
          <button
            onClick={() => setActiveTab('ai')}
            className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all ${
              activeTab === 'ai'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Cpu size={14} />
            <span>Modelos & Provedores IA</span>
          </button>

          <button
            onClick={() => setActiveTab('mcp')}
            className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all ${
              activeTab === 'mcp'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Terminal size={14} />
            <span>Servidor MCP Nativo</span>
          </button>

          <button
            onClick={() => setActiveTab('org')}
            className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all ${
              activeTab === 'org'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <ShieldCheck size={14} />
            <span>Organização & Segurança</span>
          </button>

          {currentUser?.is_system_admin && (
            <button
              onClick={() => setActiveTab('email')}
              className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all ${
                activeTab === 'email'
                  ? 'bg-mockbird-blue text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Mail size={14} />
              <span>E-mail</span>
            </button>
          )}
        </div>
      </div>

      {/* TAB 1: MODELOS & PROVEDORES IA */}
      {activeTab === 'ai' && (
        <div className="space-y-6">
          <form onSubmit={handleSaveAIConfig} className="bg-mockbird-card border border-mockbird-border rounded-2xl p-6 shadow-xl space-y-6">
            
            <div className="flex items-center justify-between pb-4 border-b border-mockbird-border">
              <div>
                <h2 className="text-base font-bold text-white flex items-center gap-2">
                  <Key size={18} className="text-mockbird-cyan" />
                  Conexão de Provedores & Modelos Customizados (BYOK)
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Conecte qualquer provedor ou modelo aberto/proprietário sem restrições.
                </p>
              </div>

              {saveSuccess && (
                <div className="bg-emerald-500/10 border border-emerald-500/40 text-emerald-300 text-xs px-3 py-1.5 rounded-lg flex items-center gap-1.5 animate-in fade-in">
                  <CheckCircle2 size={14} />
                  <span>Configuração Salva!</span>
                </div>
              )}
            </div>

            {/* Provedor Preset Grid */}
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2.5">
                Selecione o Provedor ou Modo de Conexão
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {PRESET_PROVIDERS.map((prov) => {
                  const isSelected = providerType === prov.id;
                  return (
                    <div
                      key={prov.id}
                      onClick={() => handleProviderChange(prov.id)}
                      className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                        isSelected
                          ? 'bg-mockbird-blue/15 border-mockbird-cyan text-white shadow-md shadow-mockbird-blue/10 ring-1 ring-mockbird-cyan/50'
                          : 'bg-mockbird-surface border-mockbird-border hover:border-slate-500 text-slate-300'
                      }`}
                    >
                      <div className="font-semibold text-xs flex items-center justify-between">
                        <span>{prov.name}</span>
                        {isSelected && <Check size={14} className="text-mockbird-cyan" />}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono mt-1 truncate">
                        {prov.defaultUrl}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Base URL & API Key */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                  Endpoint Base URL (API Endpoint)
                </label>
                <div className="relative">
                  <Globe size={15} className="absolute left-3.5 top-3 text-slate-500" />
                  <input
                    type="text"
                    required
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://api.openai.com/v1 ou URL customizada"
                    className="w-full pl-9 pr-3.5 py-2.5 bg-mockbird-surface border border-mockbird-border rounded-lg text-xs font-mono text-white focus:outline-none focus:border-mockbird-cyan focus:ring-1 focus:ring-mockbird-cyan transition-all"
                  />
                </div>
                <p className="text-[10px] text-slate-400 mt-1">
                  Pode ser qualquer endpoint compatível com OpenAI (ex: DeepSeek, Groq, Together, Ollama, LMStudio).
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                  API Key / Chave de Acesso
                </label>
                <div className="relative">
                  <Key size={15} className="absolute left-3.5 top-3 text-slate-500" />
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={providerType === 'ollama' ? 'Opcional para Ollama local' : 'sk-...'}
                    className="w-full pl-9 pr-3.5 py-2.5 bg-mockbird-surface border border-mockbird-border rounded-lg text-xs font-mono text-white focus:outline-none focus:border-mockbird-cyan focus:ring-1 focus:ring-mockbird-cyan transition-all"
                  />
                </div>
                <p className="text-[10px] text-slate-400 mt-1">
                  Armazenada com isolamento do tenant da sua organização.
                </p>
              </div>
            </div>

            {/* Gerenciamento de Modelos Customizados */}
            <div className="bg-mockbird-surface border border-mockbird-border rounded-xl p-5 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                    <Sparkles size={14} className="text-mockbird-cyan" />
                    Modelos Customizados Cadastrados
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Defina qualquer modelo que desejar. O modelo com estrela será usado como padrão no editor.
                  </p>
                </div>

                <div className="text-xs text-slate-400">
                  Padrão atual: <span className="font-mono font-bold text-mockbird-cyan">{defaultModel}</span>
                </div>
              </div>

              {/* Input para adicionar modelo customizado qualquer */}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newModelInput}
                  onChange={(e) => setNewModelInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddCustomModel(); } }}
                  placeholder="Digite qualquer modelo: ex: deepseek/deepseek-r1, qwen-2.5-coder, etc."
                  className="flex-1 px-3.5 py-2 bg-mockbird-card border border-mockbird-border rounded-lg text-xs font-mono text-white focus:outline-none focus:border-mockbird-cyan"
                />
                <button
                  type="button"
                  onClick={() => handleAddCustomModel()}
                  className="bg-mockbird-blue hover:bg-mockbird-bluedark text-white font-semibold text-xs px-4 py-2 rounded-lg flex items-center gap-1.5 transition-all shadow-sm"
                >
                  <Plus size={14} />
                  <span>Adicionar Modelo</span>
                </button>
              </div>

              {/* Sugestões populares em 1 clique */}
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                  Modelos Recomendados para Adicionar em 1 Clique:
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {POPULAR_SUGGESTIONS.map((sug) => {
                    const exists = customModels.includes(sug.model);
                    return (
                      <button
                        key={sug.model}
                        type="button"
                        onClick={() => handleAddCustomModel(sug.model)}
                        className={`text-[10px] px-2.5 py-1 rounded-md border transition-all flex items-center gap-1 ${
                          exists
                            ? 'bg-mockbird-blue/20 border-mockbird-blue/30 text-blue-300 font-semibold cursor-default'
                            : 'bg-mockbird-card hover:bg-mockbird-cardhover border-mockbird-border text-slate-300'
                        }`}
                      >
                        {exists ? <Check size={11} className="text-blue-400" /> : <Plus size={11} />}
                        <span>{sug.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Lista dos modelos cadastrados */}
              <div className="space-y-2 pt-2">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                  Modelos Ativos no seu Workspace ({customModels.length}):
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {customModels.map((m) => {
                    const isDefault = defaultModel === m;
                    return (
                      <div
                        key={m}
                        className={`flex items-center justify-between p-2.5 rounded-lg border text-xs font-mono transition-all ${
                          isDefault
                            ? 'bg-mockbird-blue/20 border-mockbird-cyan text-white shadow-sm'
                            : 'bg-mockbird-card border-mockbird-border text-slate-300'
                        }`}
                      >
                        <span className="truncate mr-2 font-medium" title={m}>
                          {m}
                        </span>

                        <div className="flex items-center gap-1.5 shrink-0">
                          {isDefault ? (
                            <span className="bg-mockbird-cyanbadge text-slate-100 text-[10px] font-sans font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                              <Star size={10} className="fill-slate-100" />
                              Padrão
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleSetDefaultModel(m)}
                              className="text-[10px] font-sans text-slate-400 hover:text-white px-2 py-0.5 rounded hover:bg-slate-700 transition-all"
                              title="Definir como modelo padrão"
                            >
                              Tornar Padrão
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => handleRemoveModel(m)}
                            className="text-slate-500 hover:text-rose-400 p-1 rounded hover:bg-rose-500/10 transition-all"
                            title="Remover modelo"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Test Feedback Area */}
            {testResult && (
              <div
                className={`p-3.5 rounded-xl border text-xs flex items-start gap-2.5 ${
                  testResult.status === 'ok'
                    ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                    : 'bg-rose-500/10 border-rose-500/40 text-rose-300'
                }`}
              >
                {testResult.status === 'ok' ? (
                  <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle size={16} className="text-rose-400 shrink-0 mt-0.5" />
                )}
                <div className="flex-1 font-mono">{testResult.message}</div>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center justify-between pt-2">
              <button
                type="button"
                onClick={handleTestConnection}
                disabled={testing}
                className="bg-mockbird-surface hover:bg-mockbird-card border border-mockbird-border text-slate-200 font-semibold text-xs px-4 py-2.5 rounded-lg flex items-center gap-2 transition-all disabled:opacity-50"
              >
                <RefreshCw size={14} className={testing ? 'animate-spin text-mockbird-cyan' : ''} />
                <span>{testing ? 'Testando Conexão...' : `Testar Conexão (${defaultModel})`}</span>
              </button>

              <button
                type="submit"
                disabled={saving}
                className="bg-mockbird-blue hover:bg-mockbird-bluedark text-white font-semibold text-xs px-6 py-2.5 rounded-lg shadow-lg shadow-mockbird-blue/30 flex items-center gap-2 transition-all disabled:opacity-50"
              >
                <Check size={14} />
                <span>{saving ? 'Gravando Alterações...' : 'Salvar Configurações de IA'}</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* TAB 2: SERVIDOR MCP NATIVO */}
      {activeTab === 'mcp' && (
        <div className="space-y-6">
          <div className="bg-mockbird-card border border-mockbird-border rounded-2xl p-6 shadow-xl space-y-6">
            <div>
              <div className="inline-flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-2.5 py-0.5 rounded-full text-[11px] font-bold mb-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Endpoint Ativo: /mcp/info
              </div>
              <h2 className="text-lg font-bold text-white">Servidor MCP Nativo (Model Context Protocol)</h2>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed max-w-3xl">
                O Mockbird SaaS expõe um servidor MCP de primeira classe. Ao plugar o MCP no seu Claude Desktop, Claude Code ou Cursor AI, a inteligência artificial pode inspecionar o mapa do projeto, ler o HTML exato de qualquer tela, aplicar correções de layout e gerar o bundle de implantação final sem você precisar copiar e colar nada manualmente.
              </p>
            </div>

            {/* Claude Desktop Config Snippet */}
            <div className="bg-mockbird-surface border border-mockbird-border rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-slate-200 flex items-center gap-2 font-mono">
                  <Terminal size={14} className="text-blue-400" />
                  Claude Code / Claude Desktop (claude_desktop_config.json)
                </span>
                <button
                  type="button"
                  onClick={() => copyToClipboard(mcpClaudeConfig, 'claude')}
                  className="text-xs text-mockbird-cyan hover:underline flex items-center gap-1 font-sans"
                >
                  {copiedMcp === 'claude' ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                  <span>{copiedMcp === 'claude' ? 'Copiado!' : 'Copiar JSON'}</span>
                </button>
              </div>
              <pre className="text-xs font-mono text-slate-300 bg-mockbird-bg p-3.5 rounded-lg border border-mockbird-border overflow-x-auto">
                {mcpClaudeConfig}
              </pre>
            </div>

            {/* Cursor Config Snippet */}
            <div className="bg-mockbird-surface border border-mockbird-border rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-slate-200 flex items-center gap-2 font-mono">
                  <Terminal size={14} className="text-purple-400" />
                  Cursor AI (.cursor/settings.json)
                </span>
                <button
                  type="button"
                  onClick={() => copyToClipboard(mcpCursorConfig, 'cursor')}
                  className="text-xs text-mockbird-cyan hover:underline flex items-center gap-1 font-sans"
                >
                  {copiedMcp === 'cursor' ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                  <span>{copiedMcp === 'cursor' ? 'Copiado!' : 'Copiar JSON'}</span>
                </button>
              </div>
              <pre className="text-xs font-mono text-slate-300 bg-mockbird-bg p-3.5 rounded-lg border border-mockbird-border overflow-x-auto">
                {mcpCursorConfig}
              </pre>
            </div>

            {/* MCP Tools Guide */}
            <div>
              <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider mb-3">
                Ferramentas MCP Nativas Disponíveis:
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="bg-mockbird-surface border border-mockbird-border p-3 rounded-lg">
                  <div className="font-mono font-bold text-mockbird-cyan mb-1">get_project_map</div>
                  <div className="text-slate-400 text-[11px]">
                    Retorna a árvore do projeto com todas as telas, IDs, slugs e metadados de layout.
                  </div>
                </div>

                <div className="bg-mockbird-surface border border-mockbird-border p-3 rounded-lg">
                  <div className="font-mono font-bold text-mockbird-cyan mb-1">get_screen</div>
                  <div className="text-slate-400 text-[11px]">
                    Obtém o código HTML, CSS, JS e Design Tokens em tempo real de uma tela específica.
                  </div>
                </div>

                <div className="bg-mockbird-surface border border-mockbird-border p-3 rounded-lg">
                  <div className="font-mono font-bold text-mockbird-cyan mb-1">update_screen_html</div>
                  <div className="text-slate-400 text-[11px]">
                    Aplica patches ou substituições no HTML da tela mantendo o histórico de revisões.
                  </div>
                </div>

                <div className="bg-mockbird-surface border border-mockbird-border p-3 rounded-lg">
                  <div className="font-mono font-bold text-mockbird-cyan mb-1">get_implementation_bundle</div>
                  <div className="text-slate-400 text-[11px]">
                    Facilitador de implantação: exporta todos os componentes e tokens empacotados para código de produção.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: ORGANIZAÇÃO & SEGURANÇA */}
      {activeTab === 'org' && (
        <div className="bg-mockbird-card border border-mockbird-border rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <ShieldCheck size={18} className="text-emerald-400" />
              Segurança do SaaS & Isolamento Multi-Tenant
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Todos os recursos, protótipos, comentários e chaves pertencem estritamente à sua organização.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="bg-mockbird-surface border border-mockbird-border p-4 rounded-xl">
              <div className="text-slate-400 mb-1">Licença do Software</div>
              <div className="text-white font-bold text-sm">MIT / SaaS Open Core</div>
              <div className="text-[11px] text-slate-500 mt-1">Uso livre sem cobrança de mensalidade inicial.</div>
            </div>

            <div className="bg-mockbird-surface border border-mockbird-border p-4 rounded-xl">
              <div className="text-slate-400 mb-1">Ambiente de Execução</div>
              <div className="text-emerald-400 font-bold text-sm">Homologação Ativa (Porta 8082)</div>
              <div className="text-[11px] text-slate-500 mt-1">Testes isolados antes da publicação em produção.</div>
            </div>
          </div>

          {/* Plano de IA da organização */}
          <div className="border-t border-mockbird-border pt-6 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Sparkles size={16} className="text-mockbird-cyan" /> Plano de IA
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  O limite do plano prevalece sobre o limite individual de cada usuário.
                </p>
              </div>
              {usage && (
                <div className="text-right text-xs text-slate-400">
                  <div className="font-mono text-white">
                    {Number(usage.tokens_used_month).toLocaleString('pt-BR')} /{' '}
                    {Number(usage.monthly_token_limit).toLocaleString('pt-BR')} tokens
                  </div>
                  <div className="w-48 h-1.5 bg-mockbird-bg rounded-full mt-1 overflow-hidden">
                    <div
                      className="h-full bg-mockbird-blue"
                      style={{
                        width: `${Math.min(100, (usage.tokens_used_month / Math.max(1, usage.monthly_token_limit)) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {plans.map(plan => {
                const isCurrent = usage?.plan?.slug === plan.slug;
                return (
                  <div
                    key={plan.slug}
                    className={`p-4 rounded-xl border flex flex-col gap-2 ${
                      isCurrent
                        ? 'bg-mockbird-blue/10 border-mockbird-cyan'
                        : 'bg-mockbird-surface border-mockbird-border'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-white text-sm">{plan.name}</span>
                      {isCurrent && <Check size={14} className="text-mockbird-cyan" />}
                    </div>
                    <div className="text-[11px] text-slate-400">{plan.description}</div>
                    <div className="text-xs text-slate-300 font-mono">
                      {Number(plan.monthly_token_limit).toLocaleString('pt-BR')} tokens/mês
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {plan.price_cents ? `R$ ${(plan.price_cents / 100).toFixed(2)}/mês` : 'Grátis'}
                    </div>
                    <button
                      type="button"
                      disabled={isCurrent || assigningPlan !== null || (userRole !== 'owner' && !isCurrent)}
                      onClick={() => handleAssignPlan(plan.slug)}
                      className={`mt-auto text-xs font-semibold py-1.5 rounded-lg transition-all disabled:opacity-40 ${
                        isCurrent
                          ? 'bg-mockbird-card text-slate-300'
                          : 'bg-mockbird-blue hover:bg-mockbird-bluedark text-white'
                      }`}
                    >
                      {isCurrent ? 'Plano atual' : assigningPlan === plan.slug ? 'Aplicando…' : 'Usar este plano'}
                    </button>
                  </div>
                );
              })}
            </div>
            {userRole && userRole !== 'owner' && (
              <p className="text-[11px] text-slate-500">Apenas o owner da organização pode trocar de plano.</p>
            )}
          </div>
        </div>
      )}

      {activeTab === 'email' && currentUser?.is_system_admin && (
        <div className="space-y-6">
          <EmailSettingsPanel />
          <p className="text-[11px] text-slate-500 flex items-center gap-2">
            <ShieldCheck size={13} />
            Apenas o administrador do sistema (primeira conta criada) vê esta aba. As credenciais são cifradas no banco.
          </p>
        </div>
      )}
    </div>
  );
};
