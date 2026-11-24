import { useState, useEffect } from 'react';
import { Palette, Sun, Moon, Sliders, Check } from 'lucide-react';

interface DesignTokensProps {
  projectId: string;
  lightTokens?: Record<string, string>;
  darkTokens?: Record<string, string>;
  currentTheme?: 'light' | 'dark';
  onThemeChange?: (theme: 'light' | 'dark') => void;
  onTokensUpdate?: (tokens: Record<string, string>) => void;
  onSave?: (light: Record<string, string>, dark: Record<string, string>) => Promise<void>;
}

export function TokensPanel({
  projectId,
  lightTokens,
  darkTokens,
  currentTheme,
  onThemeChange,
  onTokensUpdate,
  onSave
}: DesignTokensProps) {
  const [activeTheme, setActiveTheme] = useState<'light' | 'dark'>(currentTheme || 'dark');
  const [currentLight, setCurrentLight] = useState<Record<string, string>>(lightTokens || {
    'color-primary': '#2563eb',
    'color-bg': '#ffffff',
    'color-surface': '#f8fafc',
    'color-text': '#0f172a',
    'color-border': '#e2e8f0',
  });
  const [currentDark, setCurrentDark] = useState<Record<string, string>>(darkTokens || {
    'color-primary': '#2563eb',
    'color-bg': '#0b1120',
    'color-surface': '#1e293b',
    'color-text': '#f8fafc',
    'color-border': '#334155',
  });
  const [saving, setSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    if (currentTheme && currentTheme !== activeTheme) {
      setActiveTheme(currentTheme);
    }
  }, [currentTheme]);

  useEffect(() => {
    if (lightTokens) setCurrentLight(lightTokens);
  }, [lightTokens]);

  useEffect(() => {
    if (darkTokens) setCurrentDark(darkTokens);
  }, [darkTokens]);

  useEffect(() => {
    if (projectId && !lightTokens && !darkTokens) {
      fetch(`/api/tokens/${projectId}`)
        .then(r => r.json())
        .then(d => {
          const light = d.light_tokens || d.light_theme;
          const dark = d.dark_tokens || d.dark_theme;
          if (light && Object.keys(light).length > 0) setCurrentLight(light);
          if (dark && Object.keys(dark).length > 0) setCurrentDark(dark);
        })
        .catch(console.error);
    }
  }, [projectId, lightTokens, darkTokens]);

  const activeTokens = activeTheme === 'light' ? currentLight : currentDark;

  const handleThemeToggle = (theme: 'light' | 'dark') => {
    setActiveTheme(theme);
    if (onThemeChange) onThemeChange(theme);
    if (onTokensUpdate) {
      onTokensUpdate(theme === 'light' ? currentLight : currentDark);
    }
  };

  const handleChange = (key: string, value: string) => {
    if (activeTheme === 'light') {
      const updated = { ...currentLight, [key]: value };
      setCurrentLight(updated);
      if (onTokensUpdate) onTokensUpdate(updated);
    } else {
      const updated = { ...currentDark, [key]: value };
      setCurrentDark(updated);
      if (onTokensUpdate) onTokensUpdate(updated);
    }
    setSavedSuccess(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (onSave) {
        await onSave(currentLight, currentDark);
      } else {
        await fetch(`/api/tokens/${projectId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            light_tokens: currentLight,
            dark_tokens: currentDark,
            shared_tokens: {},
            light_theme: currentLight,
            dark_theme: currentDark
          })
        });
      }
      setSavedSuccess(true);
      setTimeout(() => setSavedSuccess(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  const colorLabels: Record<string, string> = {
    'color-primary': 'Cor Primária (Brand)',
    'color-bg': 'Fundo Principal (Background)',
    'color-surface': 'Superfície (Cards & Modais)',
    'color-text': 'Texto Principal',
    'color-border': 'Bordas & Linhas'
  };

  return (
    <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full overflow-y-auto p-4 space-y-5 select-none">
      <div className="flex items-center justify-between border-b border-mockbird-border pb-3">
        <h3 className="font-bold text-xs uppercase tracking-wider flex items-center gap-2 text-white">
          <Palette className="h-4 w-4 text-mockbird-cyan" />
          Design Tokens
        </h3>
        
        {/* Alternador Light/Dark */}
        <div className="flex rounded-lg bg-mockbird-card p-0.5 border border-mockbird-border">
          <button 
            onClick={() => handleThemeToggle('light')}
            className={`p-1.5 rounded-md text-xs transition ${activeTheme === 'light' ? 'bg-mockbird-blue text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
            title="Ver Tokens Claros"
          >
            <Sun className="h-3.5 w-3.5" />
          </button>
          <button 
            onClick={() => handleThemeToggle('dark')}
            className={`p-1.5 rounded-md text-xs transition ${activeTheme === 'dark' ? 'bg-mockbird-blue text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
            title="Ver Tokens Escuros"
          >
            <Moon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="space-y-3.5">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span className="font-bold uppercase tracking-wider text-[10px] text-mockbird-cyan">
            {activeTheme === 'light' ? 'Tema Claro (Light)' : 'Tema Escuro (Dark)'}
          </span>
          <span className="text-[10px] font-mono text-slate-500">CSS Tokens</span>
        </div>

        {Object.entries(activeTokens).map(([tokenKey, tokenValue]) => (
          <div key={tokenKey} className="space-y-1.5 bg-mockbird-card p-2.5 rounded-xl border border-mockbird-border">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-300">
                {colorLabels[tokenKey] || tokenKey}
              </label>
              <span className="text-[10px] font-mono text-slate-400">
                var(--{tokenKey})
              </span>
            </div>
            <div className="flex items-center gap-2">
              <input 
                type="color" 
                value={tokenValue}
                onChange={(e) => handleChange(tokenKey, e.target.value)}
                className="h-7 w-8 rounded cursor-pointer bg-transparent border-0 p-0"
              />
              <input 
                type="text" 
                value={tokenValue}
                onChange={(e) => handleChange(tokenKey, e.target.value)}
                className="flex-1 px-2.5 py-1 text-xs font-mono rounded bg-mockbird-surface border border-mockbird-border text-slate-200 focus:outline-none focus:border-mockbird-cyan"
              />
            </div>
          </div>
        ))}
      </div>

      {/* Amostra Visual Viva com as Variáveis Aplicadas */}
      <div 
        className="p-4 rounded-xl border shadow-lg space-y-2.5 transition"
        style={{
          backgroundColor: activeTokens['color-surface'] || '#1e293b',
          borderColor: activeTokens['color-border'] || '#334155',
          color: activeTokens['color-text'] || '#f8fafc',
        }}
      >
        <span className="text-[10px] font-bold uppercase tracking-wider opacity-60">Amostra do Design System</span>
        <h4 className="text-sm font-bold">Título de Exemplo</h4>
        <p className="text-xs opacity-75">O Mockbird reflete estas variáveis nativamente no canvas.</p>
        <button 
          className="w-full py-1.5 px-3 rounded-lg text-xs font-semibold text-white shadow-sm transition"
          style={{ backgroundColor: activeTokens['color-primary'] || '#2563eb' }}
        >
          Botão com --color-primary
        </button>
      </div>

      <button 
        onClick={handleSave}
        disabled={saving}
        className="w-full py-2 bg-mockbird-blue hover:bg-mockbird-bluedark disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 shadow-md shadow-mockbird-blue/30 transition-all"
      >
        {savedSuccess ? (
          <>
            <Check className="h-4 w-4" />
            <span>Tokens Atualizados!</span>
          </>
        ) : (
          <>
            <Sliders className="h-4 w-4" />
            <span>{saving ? 'Gravando...' : 'Salvar Alterações nos Tokens'}</span>
          </>
        )}
      </button>
    </div>
  );
}
