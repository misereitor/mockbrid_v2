import React, { useState, useEffect, useRef } from 'react';
import { 
  Palette, 
  Code2, 
  Sparkles, 
  Sliders, 
  Monitor, 
  Tablet, 
  Smartphone, 
  Plus, 
  Save, 
  MonitorPlay, 
  Database, 
  Check, 
  ChevronRight,
  Layers,
  MessageSquare,
  Copy,
  PanelRightClose,
  X,
  History
} from 'lucide-react';
import { CanvasEditor, CanvasEditorHandle, SelectedElementInfo } from '../CanvasEditor';
import { TokensPanel } from '../TokensPanel';
import { AIChatPanel } from '../AIChatPanel';
import { ScenariosManager } from '../ScenariosManager';
import { ComponentsCatalogPanel } from '../components/ComponentsCatalogPanel';
import { CommentsPanel } from '../components/CommentsPanel';
import { InspectorPanel } from '../components/InspectorPanel';
import { HistoryPanel } from '../components/HistoryPanel';

interface ScreenData {
  id: string;
  name: string;
  slug: string;
  html_content: string;
  css_content?: string;
  js_content?: string;
  is_main?: boolean;
}

interface ProjectData {
  id: string;
  name: string;
  slug: string;
  screens?: ScreenData[];
}

interface EditorPageProps {
  project: ProjectData;
  onOpenPresentation: (slug: string) => void;
  onNotify?: (msg: string) => void;
}

const VIEWPORT_SIZES = {
  desktop: { label: 'Desktop 1440px', width: 1440, height: 900, icon: Monitor },
  tablet: { label: 'Tablet 768px', width: 768, height: 1024, icon: Tablet },
  mobile: { label: 'Mobile 375px', width: 375, height: 812, icon: Smartphone }
};

const PANEL_TABS: { id: ActiveEditorTab; label: string; icon: React.ElementType }[] = [
  { id: 'ai', label: 'IA', icon: Sparkles },
  { id: 'visual', label: 'Inspector', icon: Sliders },
  { id: 'blocks', label: 'Blocos', icon: Layers },
  { id: 'code', label: 'Código', icon: Code2 },
  { id: 'tokens', label: 'Tokens', icon: Palette },
  { id: 'comments', label: 'Comentários', icon: MessageSquare },
  { id: 'history', label: 'Histórico', icon: History },
  { id: 'scenarios', label: 'Cenários', icon: Database },
];

type ActiveEditorTab = 'ai' | 'visual' | 'blocks' | 'code' | 'tokens' | 'comments' | 'history' | 'scenarios';

export const EditorPage: React.FC<EditorPageProps> = ({
  project,
  onOpenPresentation,
}) => {
  const [screens, setScreens] = useState<ScreenData[]>(project.screens || []);
  const [currentScreenIndex, setCurrentScreenIndex] = useState(0);
  const [activeTab, setActiveTab] = useState<ActiveEditorTab | null>('ai'); // Aberto na IA por padrão
  const [viewport, setViewport] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');
  const [tokenTheme, setTokenTheme] = useState<'light' | 'dark'>('dark');
  const [tokens, setTokens] = useState<Record<string, string>>({
    'color-primary': '#2563eb',
    'color-bg': '#0b1120',
    'color-surface': '#1e293b',
    'color-text': '#f8fafc',
    'color-border': '#334155',
    'font-body': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
  });
  
  const [saving, setSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [showAddScreen, setShowAddScreen] = useState(false);
  const [newScreenName, setNewScreenName] = useState('');
  const [aiPromptInstruction, setAiPromptInstruction] = useState<string>('');
  const [codeMode, setCodeMode] = useState<'html' | 'jsx' | 'css'>('html');
  const [copiedCode, setCopiedCode] = useState(false);
  const [selectedElement, setSelectedElement] = useState<SelectedElementInfo | null>(null);
  const canvasEditorRef = useRef<CanvasEditorHandle>(null);

  useEffect(() => {
    fetch(`/api/projects/${project.id}/screens`)
      .then(r => (r.ok ? r.json() : []))
      .then((list: any[]) => {
        if (Array.isArray(list) && list.length > 0) {
          setScreens(list.map(sc => ({ ...sc, is_main: sc.is_entry ?? sc.is_main })));
        }
      })
      .catch(console.error);

    fetch(`/api/tokens/${project.id}`)
      .then(r => r.json())
      .then(tokData => {
        if (tokData && tokData.dark_theme) {
          setTokens(tokData.dark_theme);
        }
      })
      .catch(console.error);
  }, [project.id]);

  const activeScreen = screens[currentScreenIndex] || {
    id: 'temp',
    name: 'Tela Principal',
    slug: 'main',
    html_content: '<div class="p-8 text-center"><h1 class="text-2xl font-bold">Mockbird SaaS</h1></div>'
  };

  const handleHtmlChange = (newHtml: string) => {
    setScreens(prev => {
      const copy = [...prev];
      if (copy[currentScreenIndex]) {
        copy[currentScreenIndex] = { ...copy[currentScreenIndex], html_content: newHtml };
      }
      return copy;
    });
  };

  const handleApplyAiPatch = async (newHtml: string) => {
    handleHtmlChange(newHtml);
    if (activeScreen.id && activeScreen.id !== 'temp') {
      try {
        await fetch(`/api/screens/${activeScreen.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            html_content: newHtml,
            css_content: activeScreen.css_content || '',
            js_content: activeScreen.js_content || ''
          })
        });
        setSavedSuccess(true);
        setTimeout(() => setSavedSuccess(false), 2500);
      } catch (err) {
        console.error('Erro no auto-save da IA:', err);
      }
    }
  };

  const handleInsertBlock = (blockHtml: string) => {
    const updated = (activeScreen.html_content || '').trim() + '\n\n' + blockHtml;
    handleApplyAiPatch(updated);
  };

  const handleSendCommentToAI = (commentText: string) => {
    setAiPromptInstruction(commentText);
    setActiveTab('ai');
  };

  const handleSaveScreen = async () => {
    if (!activeScreen.id || activeScreen.id === 'temp') return;
    setSaving(true);
    try {
      await fetch(`/api/screens/${activeScreen.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          html_content: activeScreen.html_content,
          css_content: activeScreen.css_content || '',
          js_content: activeScreen.js_content || ''
        })
      });
      setSavedSuccess(true);
      setTimeout(() => setSavedSuccess(false), 2000);
    } catch (e) {
      console.error('Erro ao salvar tela:', e);
    } finally {
      setSaving(false);
    }
  };

  const handleCreateScreen = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newScreenName.trim()) return;
    const slug = newScreenName.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]/g, '');

    try {
      const res = await fetch(`/api/projects/${project.id}/screens`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newScreenName.trim(),
          slug: slug || `screen-${Date.now()}`,
          html_content: `
            <div class="min-h-screen p-8 bg-[var(--color-bg)] text-[var(--color-text)]">
              <div class="max-w-4xl mx-auto space-y-6">
                <div class="flex items-center justify-between pb-6 border-b border-[var(--color-border)]">
                  <h1 class="text-2xl font-bold">${newScreenName.trim()}</h1>
                  <button class="px-4 py-2 bg-[var(--color-primary)] text-white text-xs font-semibold rounded-lg shadow-sm">
                    Ação Principal
                  </button>
                </div>
                <div class="p-6 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl">
                  <p class="text-sm opacity-80">Nova tela configurada no projeto ${project.name}. Edite livremente pelo canvas ou código.</p>
                </div>
              </div>
            </div>
          `
        })
      });
      if (res.ok) {
        const created = await res.json();
        setScreens(prev => [...prev, { ...created, is_main: created.is_entry }]);
        setCurrentScreenIndex(screens.length);
        setNewScreenName('');
        setShowAddScreen(false);
      }
    } catch (err) {
      console.error('Erro ao criar tela:', err);
    }
  };

  const handleDeleteScreen = async (screenId: string, screenName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (screens.length <= 1) return;
    if (!window.confirm(`Tem certeza que deseja excluir a tela "${screenName}"?`)) return;
    try {
      const res = await fetch(`/api/screens/${screenId}`, { method: 'DELETE' });
      if (res.ok) {
        const nextScreens = screens.filter(s => s.id !== screenId);
        setScreens(nextScreens);
        setCurrentScreenIndex(0);
      }
    } catch (err) {
      console.error('Erro ao excluir tela:', err);
    }
  };

  const handleDuplicateScreen = async (screenId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch(`/api/screens/${screenId}/duplicate`, { method: 'POST' });
      if (!res.ok) throw new Error('Falha ao duplicar tela');
      const newScreen = await res.json();
      setScreens(prev => [...prev, newScreen]);
      setCurrentScreenIndex(screens.length);
    } catch (err: any) {
      alert(err.message || 'Erro ao duplicar tela');
    }
  };

  const vp = VIEWPORT_SIZES[viewport];
  const cleanJsx = `export function ${activeScreen.name.replace(/\s+/g, '')}Screen() {\n  return (\n    ${activeScreen.html_content.replace(/class="/g, 'className="')}\n  );\n}`;
  const cssTokensCode = `:root {\n${Object.entries(tokens).map(([k, v]) => `  --${k}: ${v};`).join('\n')}\n}`;

  const copyCodeToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-mockbird-bg">
      {/* Barra superior */}
      <div className="h-12 bg-mockbird-surface border-b border-mockbird-border px-3 flex items-center justify-between gap-4 select-none shrink-0 z-30">
        {/* Projeto + telas */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[13px] font-medium text-slate-200 truncate max-w-[180px]">{project.name}</span>
          <ChevronRight size={13} className="text-slate-600 shrink-0" />
          <div className="flex items-center gap-0.5 overflow-x-auto" role="tablist" aria-label="Telas do projeto">
            {screens.map((s, idx) => (
              <div
                key={s.id || idx}
                role="tab"
                aria-selected={idx === currentScreenIndex}
                onClick={() => setCurrentScreenIndex(idx)}
                className={`group px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors duration-150 flex items-center gap-1.5 cursor-pointer ${
                  idx === currentScreenIndex
                    ? 'bg-mockbird-card text-white'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-mockbird-card/60'
                }`}
              >
                {s.is_main && <span className="text-amber-400">★</span>}
                <span>{s.name}</span>
                <button
                  type="button"
                  onClick={(e) => handleDuplicateScreen(s.id, e)}
                  className="opacity-0 group-hover:opacity-100 hover:text-mockbird-cyan p-0.5 rounded transition text-slate-500"
                  title="Duplicar tela"
                >
                  <Copy size={11} />
                </button>
                {screens.length > 1 && (
                  <button
                    type="button"
                    onClick={(e) => handleDeleteScreen(s.id, s.name, e)}
                    className="opacity-0 group-hover:opacity-100 hover:text-rose-400 p-0.5 rounded transition text-slate-500"
                    title="Excluir tela"
                  >
                    <X size={11} />
                  </button>
                )}
              </div>
            ))}
            <button onClick={() => setShowAddScreen(true)} className="mb-btn-ghost !p-1.5" title="Adicionar tela" aria-label="Adicionar tela">
              <Plus size={14} />
            </button>
          </div>
        </div>

        {/* Viewport */}
        <div className="hidden lg:flex items-center gap-0.5 p-0.5 rounded-md bg-mockbird-bg border border-mockbird-border">
          {(['desktop', 'tablet', 'mobile'] as const).map((mode) => {
            const Icon = VIEWPORT_SIZES[mode].icon;
            const active = viewport === mode;
            return (
              <button
                key={mode}
                onClick={() => setViewport(mode)}
                className={`p-1.5 rounded transition-colors duration-150 ${active ? 'bg-mockbird-card text-white' : 'text-slate-500 hover:text-slate-200'}`}
                title={VIEWPORT_SIZES[mode].label}
                aria-label={VIEWPORT_SIZES[mode].label}
                aria-pressed={active}
              >
                <Icon size={14} />
              </button>
            );
          })}
        </div>

        {/* Ações */}
        <div className="flex items-center gap-2">
          <button onClick={() => onOpenPresentation(project.slug)} className="mb-btn-outline" title="Apresentar em tela cheia">
            <MonitorPlay size={14} /> Apresentar
          </button>
          <button
            onClick={handleSaveScreen}
            disabled={saving}
            className={savedSuccess ? 'mb-btn bg-emerald-600 text-white' : 'mb-btn-primary'}
          >
            {savedSuccess ? <Check size={14} /> : <Save size={14} />}
            {savedSuccess ? 'Salvo' : saving ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>

      {/* Nova tela (inline) */}
      {showAddScreen && (
        <div className="bg-mockbird-surface border-b border-mockbird-border px-4 py-2.5 animate-in slide-in-from-top-2 duration-150">
          <form onSubmit={handleCreateScreen} className="flex items-center gap-2 max-w-xl">
            <input
              type="text"
              required
              autoFocus
              value={newScreenName}
              onChange={(e) => setNewScreenName(e.target.value)}
              placeholder="Nome da nova tela (ex: Checkout)"
              className="mb-input !py-1.5 !text-xs"
              aria-label="Nome da nova tela"
            />
            <button type="submit" className="mb-btn-primary">Criar</button>
            <button type="button" onClick={() => setShowAddScreen(false)} className="mb-btn-ghost">Cancelar</button>
          </form>
        </div>
      )}

      {/* Editor Body */}
      <div className="flex-1 flex overflow-hidden relative">
        
        {/* Canvas Central */}
        <div className="flex-1 flex flex-col h-full overflow-hidden">
          <CanvasEditor
            ref={canvasEditorRef}
            key={activeScreen.id}
            initialHtml={activeScreen.html_content}
            tokens={tokens}
            onHtmlChange={handleHtmlChange}
            width={vp.width}
            height={vp.height}
            onElementSelected={(el) => {
              setSelectedElement(el);
              if (el && !activeTab) {
                setActiveTab('visual');
              }
            }}
            onRequestOpenTab={(tab) => setActiveTab(tab)}
            onNewCommentOnElement={(selector, snippet) => {
              setActiveTab('comments');
              if (selector) {
                setAiPromptInstruction(`Ajuste no elemento ${selector}${snippet ? ` ("${snippet}")` : ''}: `);
              }
            }}
          />
        </div>

        {/* Painel direito único com abas */}
        <div
          className={`${activeTab ? 'w-96' : 'w-11'} shrink-0 h-full flex ${activeTab ? 'flex-col' : 'flex-col items-center'} border-l border-mockbird-border bg-mockbird-surface transition-[width] duration-200 z-20`}
        >
          {/* Faixa de abas */}
          <div className={`${activeTab ? 'h-11 px-1.5 border-b border-mockbird-border flex-row' : 'py-2 flex-col'} flex items-center gap-0.5 shrink-0`} role="tablist" aria-label="Painéis do editor">
            {PANEL_TABS.map(({ id, label, icon: Icon }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTab(id)}
                  title={label}
                  className={`flex items-center gap-1.5 rounded-md text-xs font-medium transition-colors duration-150 ${
                    activeTab ? (active ? 'px-2.5 py-1.5 bg-mockbird-card text-white' : 'p-1.5 text-slate-500 hover:text-slate-200 hover:bg-mockbird-card/60') : 'p-2 text-slate-500 hover:text-slate-200 hover:bg-mockbird-card/60'
                  }`}
                >
                  <Icon size={15} className={active ? 'text-mockbird-cyan' : ''} />
                  {active && <span>{label}</span>}
                </button>
              );
            })}
            {activeTab && (
              <button onClick={() => setActiveTab(null)} className="ml-auto mb-btn-ghost !p-1.5" title="Recolher painel" aria-label="Recolher painel">
                <PanelRightClose size={15} />
              </button>
            )}
          </div>

          {activeTab && (
            <div className="flex-1 min-h-0 flex overflow-hidden [&>*]:!w-full [&>*]:!border-l-0 [&>*]:!shadow-none">
            {activeTab === 'ai' && (
              <AIChatPanel
                projectId={project.id}
                currentHtml={activeScreen.html_content}
                selectedElement={selectedElement}
                onClearSelectedElement={() => setSelectedElement(null)}
                onApplyHtml={handleApplyAiPatch}
                onApplyElementPatch={(patch, target) => {
                  canvasEditorRef.current?.patchElement?.(patch, target);
                }}
                initialPrompt={aiPromptInstruction}
                onClose={() => setActiveTab(null)}
              />
            )}

            {activeTab === 'visual' && (
              <InspectorPanel
                selectedElement={selectedElement}
                onApplyStylePatch={(patch) => canvasEditorRef.current?.applyStylePatch(patch)}
                onSendAction={(actionType) => canvasEditorRef.current?.sendAction(actionType)}
                onClose={() => setActiveTab(null)}
              />
            )}

            {activeTab === 'blocks' && (
              <ComponentsCatalogPanel onInsertComponent={handleInsertBlock} />
            )}

            {activeTab === 'comments' && (
              <CommentsPanel
                screenId={activeScreen.id}
                onSendToAI={handleSendCommentToAI}
              />
            )}

            {activeTab === 'code' && (
              <div className="w-96 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full p-4 space-y-3 shrink-0 select-none shadow-2xl">
                <div className="flex items-center justify-between border-b border-mockbird-border pb-2.5">
                  <div className="flex items-center gap-1 bg-mockbird-card border border-mockbird-border p-0.5 rounded-lg text-xs">
                    <button
                      onClick={() => setCodeMode('html')}
                      className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                        codeMode === 'html' ? 'bg-mockbird-blue text-white shadow-sm' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      HTML
                    </button>
                    <button
                      onClick={() => setCodeMode('jsx')}
                      className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                        codeMode === 'jsx' ? 'bg-mockbird-blue text-white shadow-sm' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      React JSX
                    </button>
                    <button
                      onClick={() => setCodeMode('css')}
                      className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                        codeMode === 'css' ? 'bg-mockbird-blue text-white shadow-sm' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      CSS Tokens
                    </button>
                  </div>

                  <button
                    onClick={() => copyCodeToClipboard(codeMode === 'html' ? activeScreen.html_content : codeMode === 'jsx' ? cleanJsx : cssTokensCode)}
                    className="text-xs text-mockbird-cyan hover:underline flex items-center gap-1"
                    title="Copiar código"
                  >
                    {copiedCode ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                    <span>{copiedCode ? 'Copiado!' : 'Copiar'}</span>
                  </button>
                </div>

                {codeMode === 'html' ? (
                  <textarea
                    value={activeScreen.html_content}
                    onChange={(e) => handleHtmlChange(e.target.value)}
                    className="flex-1 w-full bg-mockbird-bg border border-mockbird-border rounded-xl p-3 text-xs font-mono text-slate-200 focus:outline-none focus:border-mockbird-cyan resize-none leading-relaxed"
                    spellCheck={false}
                  />
                ) : codeMode === 'jsx' ? (
                  <pre className="flex-1 w-full bg-mockbird-bg border border-mockbird-border rounded-xl p-3 text-xs font-mono text-slate-200 overflow-auto leading-relaxed">
                    {cleanJsx}
                  </pre>
                ) : (
                  <pre className="flex-1 w-full bg-mockbird-bg border border-mockbird-border rounded-xl p-3 text-xs font-mono text-slate-200 overflow-auto leading-relaxed">
                    {cssTokensCode}
                  </pre>
                )}

                <div className="text-[11px] text-slate-400">
                  {codeMode === 'html'
                    ? 'Edite diretamente o HTML da tela com atualização em tempo real.'
                    : 'Código pronto para importar na sua aplicação React de produção.'}
                </div>
              </div>
            )}

            {activeTab === 'tokens' && (
              <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full shrink-0 shadow-2xl">
                <TokensPanel
                  projectId={project.id}
                  currentTheme={tokenTheme}
                  onThemeChange={setTokenTheme}
                  onTokensUpdate={setTokens}
                />
              </div>
            )}

            {activeTab === 'history' && activeScreen && (
              <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full shrink-0 shadow-2xl">
                <HistoryPanel
                  screenId={activeScreen.id}
                  onRevertSuccess={(revertedScreen) => {
                    setScreens(prev => prev.map((s, idx) => idx === currentScreenIndex ? { ...s, ...revertedScreen } : s));
                  }}
                  onClose={() => setActiveTab(null)}
                />
              </div>
            )}

            {activeTab === 'scenarios' && (
              <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full shrink-0 shadow-2xl">
                <ScenariosManager
                  projectId={project.id}
                  onApplyScenario={(data) => console.log('Cenário:', data)}
                />
              </div>
            )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
