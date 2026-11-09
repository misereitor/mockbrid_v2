import React, { useState, useEffect } from 'react';
import { Bot, Key, Sparkles, Check, Server, Copy, CheckCircle2 } from 'lucide-react';

interface AIProvider {
  id: string;
  provider_type: string;
  default_model: string;
  is_active: boolean;
  tokens_used_month: number;
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<'ai' | 'mcp'>('ai');
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [providerType, setProviderType] = useState('openai');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('gpt-4o-mini');
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);

  const fetchProviders = async () => {
    try {
      const res = await fetch('/api/ai/providers');
      if (res.ok) {
        const data = await res.json();
        setProviders(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  const handleSaveProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await fetch('/api/ai/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: providerType,
          api_key: apiKey,
          default_model: model
        })
      });
      if (res.ok) {
        setSuccess(true);
        setApiKey('');
        fetchProviders();
        setTimeout(() => setSuccess(false), 3000);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const mcpConfigJson = JSON.stringify({
    mcpServers: {
      mockbird: {
        command: "npx",
        args: ["-y", "@modelcontextprotocol/server-fetch", "http://127.0.0.1:8082/mcp/info"],
        env: {
          MOCKBIRD_API: "http://127.0.0.1:8082"
        }
      }
    }
  }, null, 2);

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-6">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-2xl bg-teal-500/10 text-teal-400 border border-teal-500/20 flex items-center justify-center shadow-md">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-bold text-base text-white">Configurações do SaaS</h3>
              <p className="text-xs text-slate-400">Conecte modelos de IA (BYOK) e configure integração MCP</p>
            </div>
          </div>
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 text-xs transition">
            Fechar (Esc)
          </button>
        </div>

        {/* Abas */}
        <div className="flex gap-2 border-b border-slate-800 pb-2">
          <button 
            onClick={() => setActiveTab('ai')}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition ${activeTab === 'ai' ? 'bg-teal-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Conexão com IA (LLMs)
          </button>
          <button 
            onClick={() => setActiveTab('mcp')}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition ${activeTab === 'mcp' ? 'bg-teal-600 text-white shadow-md' : 'text-slate-400 hover:text-slate-200'}`}
          >
            <Server className="h-3.5 w-3.5" />
            Servidor MCP para Agentes
          </button>
        </div>

        {/* Conteúdo Aba IA */}
        {activeTab === 'ai' && (
          <div className="space-y-5">
            <form onSubmit={handleSaveProvider} className="p-5 rounded-2xl bg-slate-950 border border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-teal-400 uppercase tracking-wider flex items-center gap-1.5">
                  <Key className="h-3.5 w-3.5" /> Conectar Provedor (BYOK)
                </span>
                <span className="text-[11px] text-slate-500 font-mono">Chaves criptografadas</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-300">Provedor</label>
                  <select 
                    value={providerType}
                    onChange={(e) => {
                      setProviderType(e.target.value);
                      if (e.target.value === 'anthropic') setModel('claude-3-5-sonnet-20241022');
                      else if (e.target.value === 'openrouter') setModel('meta-llama/llama-3.3-70b-instruct');
                      else setModel('gpt-4o-mini');
                    }}
                    className="w-full mt-1 px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none"
                  >
                    <option value="openai">OpenAI (ChatGPT)</option>
                    <option value="anthropic">Anthropic (Claude)</option>
                    <option value="openrouter">OpenRouter (Multi-modelos)</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="ollama">Ollama (Local)</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-300">Modelo Padrão</label>
                  <input 
                    type="text" 
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full mt-1 px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
                    required
                  />
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-300">Chave de API (API Key)</label>
                  <input 
                    type="password" 
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-..."
                    required
                    className="w-full mt-1 px-3 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-1">
                <button 
                  type="submit" 
                  disabled={saving}
                  className="px-5 py-2.5 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-teal-600/20"
                >
                  {saving ? 'Salvando...' : (success ? <Check className="h-4 w-4" /> : 'Salvar Chave')}
                </button>
              </div>
            </form>

            {/* Provedores Ativos */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-400">Provedores Configurados na Organização:</span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {providers.map((p) => (
                  <div key={p.id} className="p-3.5 rounded-xl bg-slate-800/40 border border-slate-800 flex items-center justify-between text-xs">
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5">
                        <CheckCircle2 className="h-3.5 w-3.5 text-teal-400" />
                        <span className="font-semibold text-slate-200 uppercase">{p.provider_type}</span>
                      </div>
                      <p className="text-[11px] font-mono text-slate-400">{p.default_model}</p>
                    </div>
                    <span className="text-[10px] text-slate-500 font-mono">
                      {p.tokens_used_month} tokens
                    </span>
                  </div>
                ))}
                {providers.length === 0 && (
                  <p className="text-xs text-slate-500 col-span-2 py-2">Nenhum provedor externo salvo ainda. O sistema usa o motor de auxílio padrão.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Conteúdo Aba MCP */}
        {activeTab === 'mcp' && (
          <div className="space-y-4">
            <div className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-teal-400 uppercase tracking-wider flex items-center gap-2">
                  <Server className="h-4 w-4" /> Configuração para Cursor, Claude Code, OpenCode
                </h4>
                <button 
                  onClick={() => {
                    navigator.clipboard.writeText(mcpConfigJson);
                    setCopiedMcp(true);
                    setTimeout(() => setCopiedMcp(false), 2000);
                  }}
                  className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium flex items-center gap-1.5 transition"
                >
                  {copiedMcp ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  {copiedMcp ? 'Copiado!' : 'Copiar JSON'}
                </button>
              </div>

              <pre className="p-3.5 rounded-xl bg-slate-900 font-mono text-xs text-teal-300 overflow-x-auto border border-slate-800">
                {mcpConfigJson}
              </pre>

              <p className="text-xs text-slate-400">
                Adicione este bloco nas configurações MCP do seu editor para que qualquer IA (Claude, Cursor, Antigravity) possa ler seus projetos e criar telas diretamente no Mockbird.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
