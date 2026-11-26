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
  Link2,
  Database,
  Check, 
  ChevronRight,
  Layers,
  LayoutGrid,
  MessageSquare,
  Copy,
  PanelRightClose,
  X,
  History,
  Image as ImageIcon,
  Wifi,
  WifiOff,
  Download,
  Undo2,
  Redo2,
  Sun,
  Moon,
  FolderPlus,
  Edit2
} from 'lucide-react';
import { CanvasEditor, CanvasEditorHandle, SelectedElementInfo } from '../CanvasEditor';
import { TokensPanel } from '../TokensPanel';
import { AIChatPanel } from '../AIChatPanel';
import { ScenariosManager } from '../ScenariosManager';
import { ComponentsCatalogPanel } from '../components/ComponentsCatalogPanel';
import { LayersPanel } from '../components/LayersPanel';
import { CommentsPanel } from '../components/CommentsPanel';
import { DevToolsDock } from '../components/DevToolsDock';
import { InspectorPanel } from '../components/InspectorPanel';
import { HistoryPanel } from '../components/HistoryPanel';
import { MediaLibraryPanel } from '../components/MediaLibraryPanel';
import { useProjectSocket } from '../lib/realtime';
import { SharePanel } from '../components/SharePanel';
import { imageHtml, uploadProjectAsset } from '../lib/assets';
import { resolveScreenIndex } from '../lib/mockNav';
import { useUndoHistory } from '../lib/useUndoHistory';
import {
  buildDesignBundle,
  designBundleFilename,
  downloadDesignBundle,
} from '../lib/designBundle';

interface ScreenData {
  id: string;
  name: string;
  slug: string;
  html_content: string;
  css_content?: string;
  js_content?: string;
  is_main?: boolean;
  width?: number;
  height?: number;
  device_type?: string;
}

interface ProjectData {
  id: string;
  name: string;
  slug: string;
  screens?: ScreenData[];
}

interface EditorPageProps {
  project: ProjectData;
  onOpenPresentation: (projectId: string) => void;
  onNotify?: (msg: string) => void;
  onNewProject?: () => void;
  onRenameProject?: (projectId: string, newName: string) => Promise<void> | void;
}

const VIEWPORT_SIZES = {
  desktop: { label: 'Desktop 1440px', width: 1440, height: 900, icon: Monitor },
  tablet: { label: 'Tablet 768px', width: 768, height: 1024, icon: Tablet },
  mobile: { label: 'Mobile 375px', width: 375, height: 812, icon: Smartphone }
};

const PANEL_TABS: { id: ActiveEditorTab; label: string; icon: React.ElementType }[] = [
  { id: 'ai', label: 'IA', icon: Sparkles },
  { id: 'visual', label: 'Inspector', icon: Sliders },
  { id: 'media', label: 'Mídia', icon: ImageIcon },
  { id: 'layers', label: 'Camadas', icon: Layers },
  { id: 'blocks', label: 'Blocos', icon: LayoutGrid },
  { id: 'code', label: 'Código', icon: Code2 },
  { id: 'tokens', label: 'Tokens', icon: Palette },
  { id: 'comments', label: 'Comentários', icon: MessageSquare },
  { id: 'history', label: 'Histórico', icon: History },
  { id: 'scenarios', label: 'Cenários', icon: Database },
];

type ActiveEditorTab = 'ai' | 'visual' | 'media' | 'layers' | 'blocks' | 'code' | 'tokens' | 'comments' | 'history' | 'scenarios';

export const EditorPage: React.FC<EditorPageProps> = ({
  project,
  onOpenPresentation,
  onNotify,
  onNewProject,
  onRenameProject,
}) => {
  const [screens, setScreens] = useState<ScreenData[]>(project.screens || []);
  const [projectName, setProjectName] = useState(project.name);
  const [sharePanelOpen, setSharePanelOpen] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameInput, setNameInput] = useState(project.name);
  const [savingName, setSavingName] = useState(false);

  useEffect(() => {
    setProjectName(project.name);
    setNameInput(project.name);
  }, [project.name]);

  const handleSaveName = async () => {
    const trimmed = nameInput.trim();
    if (!trimmed || trimmed === projectName) {
      setNameInput(projectName);
      setIsEditingName(false);
      return;
    }
    setSavingName(true);
    try {
      const res = await fetch(`/api/projects/${project.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Falha ao renomear projeto');
      }
      const data = await res.json();
      setProjectName(data.name);
      setIsEditingName(false);
      onNotify?.('Projeto renomeado com sucesso');
      onRenameProject?.(project.id, data.name);
    } catch (e: any) {
      alert(e.message || 'Erro ao renomear projeto');
      setNameInput(projectName);
    } finally {
      setSavingName(false);
    }
  };
  const [currentScreenIndex, setCurrentScreenIndex] = useState(0);
  const [activeTab, setActiveTab] = useState<ActiveEditorTab | null>('ai'); // Aberto na IA por padrão
  const [viewport, setViewport] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');
  const [tokenTheme, setTokenTheme] = useState<'light' | 'dark'>('dark');
  const [allTokens, setAllTokens] = useState<{
    light: Record<string, string>;
    dark: Record<string, string>;
    shared: Record<string, string>;
  }>({
    light: {
      'color-primary': '#2563eb',
      'color-bg': '#ffffff',
      'color-surface': '#f8fafc',
      'color-text': '#0f172a',
      'color-border': '#e2e8f0',
    },
    dark: {
      'color-primary': '#2563eb',
      'color-bg': '#0b1120',
      'color-surface': '#1e293b',
      'color-text': '#f8fafc',
      'color-border': '#334155',
    },
    shared: {
      'font-body': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }
  });
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
  const [commentsRefresh, setCommentsRefresh] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [exportingBundle, setExportingBundle] = useState<string | null>(null);
  const [showDevTools, setShowDevTools] = useState(false);
  const [devToolsDockPosition, setDevToolsDockPosition] = useState<'right' | 'bottom'>('right');
  const canvasEditorRef = useRef<CanvasEditorHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirtyRef = useRef(false);
  const activeScreenIdRef = useRef<string | undefined>(undefined);

  const activeScreen = screens[currentScreenIndex] || {
    id: 'temp',
    name: 'Tela Principal',
    slug: 'main',
    html_content: '<div class="p-8 text-center"><h1 class="text-2xl font-bold">Mockbird SaaS</h1></div>'
  };

  // Desfazer/refazer do HTML da tela ativa: cobre edições no canvas, na IA e
  // no editor de código, porque todas passam pelo mesmo estado da tela.
  const history = useUndoHistory<string>({
    key: activeScreen.id,
    value: activeScreen.html_content || '',
    onApply: (html) => {
      dirtyRef.current = true;
      setScreens(prev =>
        prev.map((s, idx) => (idx === currentScreenIndex ? { ...s, html_content: html } : s))
      );
    },
  });

  const { participants, connected } = useProjectSocket(project.id, (message) => {
    if (message.type === 'screen_updated' && message.screen_id) {
      const isActive = message.screen_id === activeScreenIdRef.current;
      if (isActive && dirtyRef.current) return;
      if (isActive) history.markExternal(message.html_content);
      setScreens(prev =>
        prev.map(s =>
          s.id === message.screen_id
            ? {
                ...s,
                html_content: message.html_content ?? s.html_content,
                css_content: message.css_content ?? s.css_content,
                js_content: message.js_content ?? s.js_content,
              }
            : s
        )
      );
    }
    if (message.type === 'comment_created' && message.comment?.screen_id === activeScreenIdRef.current) {
      setCommentsRefresh(v => v + 1);
    }
  });

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
        if (tokData) {
          const light = tokData.light_tokens || tokData.light_theme || {};
          const dark = tokData.dark_tokens || tokData.dark_theme || {};
          const shared = tokData.shared_tokens || {};
          setAllTokens(prev => {
            const nextLight = Object.keys(light).length > 0 ? light : prev.light;
            const nextDark = Object.keys(dark).length > 0 ? dark : prev.dark;
            const nextShared = Object.keys(shared).length > 0 ? shared : prev.shared;
            const active = tokenTheme === 'light' ? nextLight : nextDark;
            setTokens({ ...nextShared, ...active });
            return { light: nextLight, dark: nextDark, shared: nextShared };
          });
        }
      })
      .catch(console.error);
  }, [project.id]);

  // Atalhos de desfazer/refazer quando o foco está no editor (dentro do canvas
  // o próprio runtime encaminha o Ctrl+Z).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const active = document.activeElement as HTMLElement | null;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
        return;
      }
      if (e.key === 'F12') {
        e.preventDefault();
        setShowDevTools((v) => !v);
        return;
      }
      if (!e.ctrlKey && !e.metaKey) return;
      if (e.key === 'z' || e.key === 'Z') {
        e.preventDefault();
        if (e.shiftKey) history.redo();
        else history.undo();
      } else if (e.key === 'y' || e.key === 'Y') {
        e.preventDefault();
        history.redo();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [history.undo, history.redo]);

  // Clique em link/`data-go` no canvas: troca de tela como num mock navegável.
  const handleMockNavigate = (target: string, external?: boolean) => {
    if (external) {
      onNotify?.(`Link externo não abre dentro do mock: ${target}`);
      return;
    }
    const index = resolveScreenIndex(target, screens);
    if (index < 0) {
      onNotify?.(`Nenhuma tela corresponde a "${target}".`);
      return;
    }
    if (index === currentScreenIndex) return;
    setCurrentScreenIndex(index);
    setSelectedElement(null);
    onNotify?.(`Mock: ${screens[index].name}`);
  };

  const handleExportDesignBundle = async () => {
    if (exportingBundle) return;
    setExportingBundle('preparando…');
    try {
      const tokensRes = await fetch(`/api/tokens/${project.id}`);
      const tokenData = tokensRes.ok ? await tokensRes.json() : null;
      const bundle = await buildDesignBundle({
        project: { id: project.id, name: project.name, slug: project.slug },
        screens,
        tokens: {
          light: tokenData?.light_tokens || {},
          dark: tokenData?.dark_tokens || tokens,
          shared: tokenData?.shared_tokens || {},
        },
        onProgress: (done, total) => setExportingBundle(`${done}/${total}`),
      });
      downloadDesignBundle(bundle, designBundleFilename(project));
      onNotify?.(
        `Bundle exportado com ${bundle.screens.length} tela(s). Importe o arquivo no plugin Figma/Penpot.`,
      );
    } catch (error) {
      onNotify?.(`Falha ao exportar: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExportingBundle(null);
    }
  };

  const handleHtmlChange = (newHtml: string) => {
    dirtyRef.current = true;
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
        dirtyRef.current = false;
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
      dirtyRef.current = false;
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

  const handleUploadImage = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const asset = await uploadProjectAsset(project.id, file);
      await handleApplyAiPatch(`${(activeScreen.html_content || '').trim()}\n\n${imageHtml(asset)}`);
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar imagem');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  activeScreenIdRef.current = activeScreen.id;

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
          {isEditingName ? (
            <input
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onBlur={handleSaveName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveName();
                if (e.key === 'Escape') {
                  setNameInput(projectName);
                  setIsEditingName(false);
                }
              }}
              autoFocus
              disabled={savingName}
              className="bg-mockbird-bg border border-mockbird-cyan text-white text-[13px] px-2 py-0.5 rounded outline-none w-44 font-medium"
              placeholder="Nome do projeto"
              aria-label="Editar nome do projeto"
            />
          ) : (
            <div
              className="group/name flex items-center gap-1.5 cursor-pointer py-0.5 px-1.5 rounded hover:bg-mockbird-card transition-colors min-w-0"
              onClick={() => setIsEditingName(true)}
              title="Clique para renomear o projeto"
            >
              <span className="text-[13px] font-medium text-slate-200 truncate max-w-[180px]">
                {projectName}
              </span>
              <Edit2 size={11} className="text-slate-500 group-hover/name:text-mockbird-cyan transition-colors shrink-0 opacity-0 group-hover/name:opacity-100" />
            </div>
          )}
          {onNewProject && (
            <button
              type="button"
              onClick={onNewProject}
              className="p-1 rounded text-slate-400 hover:text-mockbird-cyan hover:bg-mockbird-card transition-colors shrink-0"
              title="Iniciar no editor"
              aria-label="Iniciar no editor"
            >
              <FolderPlus size={14} />
            </button>
          )}
          <span
            title={connected ? 'Colaboração em tempo real ativa' : 'Reconectando colaboração…'}
            className="shrink-0"
          >
            {connected ? (
              <Wifi size={12} className="text-emerald-400" />
            ) : (
              <WifiOff size={12} className="text-slate-500" />
            )}
          </span>
          {participants.length > 0 && (
            <div className="flex items-center -space-x-1.5 shrink-0" title="Pessoas neste projeto agora">
              {participants.slice(0, 4).map(p => (
                <span
                  key={p.user_id}
                  title={p.name}
                  style={{ backgroundColor: p.color }}
                  className="w-5 h-5 rounded-full text-[9px] font-bold text-white flex items-center justify-center ring-2 ring-mockbird-surface"
                >
                  {p.name?.[0]?.toUpperCase() || '?'}
                </span>
              ))}
              {participants.length > 4 && (
                <span className="w-5 h-5 rounded-full bg-slate-600 text-[9px] font-bold text-white flex items-center justify-center ring-2 ring-mockbird-surface">
                  +{participants.length - 4}
                </span>
              )}
            </div>
          )}
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

        {/* Alternador de Tema do Canvas (Light / Dark) */}
        <button
          type="button"
          onClick={() => {
            const nextTheme = tokenTheme === 'dark' ? 'light' : 'dark';
            setTokenTheme(nextTheme);
            const active = nextTheme === 'light' ? allTokens.light : allTokens.dark;
            setTokens({ ...allTokens.shared, ...active });
          }}
          className="flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-mockbird-bg border border-mockbird-border text-slate-300 hover:text-white hover:bg-mockbird-card transition text-xs"
          title={tokenTheme === 'dark' ? 'Mudar tela para tema claro' : 'Mudar tela para tema escuro'}
          aria-label="Alternar tema da tela"
        >
          {tokenTheme === 'dark' ? <Moon size={14} className="text-cyan-400" /> : <Sun size={14} className="text-amber-400" />}
          <span className="hidden xl:inline text-[11px] font-medium">{tokenTheme === 'dark' ? 'Escuro' : 'Claro'}</span>
        </button>

        {/* Ações */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-mockbird-bg border border-mockbird-border">
            <button
              type="button"
              onClick={history.undo}
              disabled={!history.canUndo}
              className="p-1.5 rounded text-slate-300 hover:text-white hover:bg-mockbird-card disabled:opacity-35 disabled:hover:bg-transparent"
              title="Desfazer (Ctrl+Z)"
              aria-label="Desfazer"
            >
              <Undo2 size={14} />
            </button>
            <button
              type="button"
              onClick={history.redo}
              disabled={!history.canRedo}
              className="p-1.5 rounded text-slate-300 hover:text-white hover:bg-mockbird-card disabled:opacity-35 disabled:hover:bg-transparent"
              title="Refazer (Ctrl+Shift+Z)"
              aria-label="Refazer"
            >
              <Redo2 size={14} />
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={(e) => handleUploadImage(e.target.files?.[0])}
          />
          <button
            onClick={() => setShowDevTools((v) => !v)}
            className={`mb-btn-outline ${showDevTools ? 'bg-mockbird-card text-mockbird-cyan border-mockbird-cyan/40' : ''}`}
            title="Alternar DevTools F12 (Console, Elementos, Rede, Estilos)"
          >
            <Code2 size={14} /> DevTools (F12)
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="mb-btn-outline"
            title="Enviar imagem e inserir na tela"
          >
            <ImageIcon size={14} /> {uploading ? 'Enviando…' : 'Imagem'}
          </button>
          <button
            onClick={handleExportDesignBundle}
            disabled={exportingBundle !== null}
            className="mb-btn-outline"
            title="Exportar bundle JSON com as camadas de cada tela para importar no Figma ou Penpot"
          >
            <Download size={14} /> {exportingBundle ? `Exportando ${exportingBundle}` : 'Figma/Penpot'}
          </button>
          <button
            onClick={() => onOpenPresentation(project.id)}
            className="mb-btn-outline"
            title="Pré-visualizar em tela cheia (só para você; não compartilha nada)"
          >
            <MonitorPlay size={14} /> Apresentar
          </button>
          <button
            onClick={() => setSharePanelOpen(true)}
            className="mb-btn-outline"
            title="Criar links de apresentação com senha, validade e nível de acesso"
          >
            <Link2 size={14} /> Compartilhar
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
        
        {/* Canvas Central e DevTools acoplado na Lateral ou na Base */}
        <div className={`flex-1 flex ${devToolsDockPosition === 'right' ? 'flex-row' : 'flex-col'} min-w-0 min-h-0 h-full relative overflow-hidden`}>
          <div className="flex-1 flex flex-col min-w-0 min-h-0 relative overflow-hidden">
            <CanvasEditor
              ref={canvasEditorRef}
              initialHtml={activeScreen.html_content}
              tokens={tokens}
              theme={tokenTheme}
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
              onNavigate={handleMockNavigate}
              onUndo={history.undo}
              onRedo={history.redo}
              onNewCommentOnElement={(selector, snippet) => {
                setActiveTab('comments');
                if (selector) {
                  setAiPromptInstruction(`Ajuste no elemento ${selector}${snippet ? ` ("${snippet}")` : ''}: `);
                }
              }}
            />
          </div>
          {showDevTools && (
            <DevToolsDock
              dockPosition={devToolsDockPosition}
              onDockChange={(pos) => setDevToolsDockPosition(pos)}
              onClose={() => setShowDevTools(false)}
            />
          )}
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

          {/* Conteúdo dos painéis. O chat fica sempre montado: trocar de aba
              não pode interromper a geração em andamento nem perder a conversa. */}
          <div className={`flex-1 min-h-0 overflow-hidden [&>*]:!w-full [&>*]:!border-l-0 [&>*]:!shadow-none ${activeTab ? 'flex' : 'hidden'}`}>
            <div className={activeTab === 'ai' ? 'flex w-full min-h-0 h-full [&>*]:!w-full [&>*]:!border-l-0 [&>*]:!shadow-none' : 'hidden'}>
              <AIChatPanel
                projectId={project.id}
                screenId={activeScreen.id}
                currentHtml={activeScreen.html_content}
                selectedElement={selectedElement}
                onClearSelectedElement={() => setSelectedElement(null)}
                onApplyHtml={handleApplyAiPatch}
                onApplyElementPatch={(patch, target) => {
                  canvasEditorRef.current?.patchElement?.(patch, target);
                }}
                initialPrompt={aiPromptInstruction}
                onCreateScreen={async (name, html) => {
                  const slug = name.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]/g, '');
                  try {
                    const res = await fetch(`/api/projects/${project.id}/screens`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        name,
                        slug: slug || `screen-${Date.now()}`,
                        html_content: html,
                      }),
                    });
                    if (res.ok) {
                      const created = await res.json();
                      setScreens((prev) => [...prev, { ...created, is_main: created.is_entry }]);
                      setCurrentScreenIndex(screens.length);
                      onNotify?.(`Tela conectada "${name}" criada com sucesso!`);
                    }
                  } catch (e) {
                    console.error('Erro ao criar tela conectada:', e);
                  }
                }}
                onClose={() => setActiveTab(null)}
              />
            </div>

            {activeTab === 'visual' && (
              <InspectorPanel
                selectedElement={selectedElement}
                screens={screens}
                onApplyStylePatch={(patch) => canvasEditorRef.current?.applyStylePatch(patch)}
                onApplyAttributes={(attrs) => canvasEditorRef.current?.updateAttributes?.(attrs)}
                onSendAction={(actionType) => canvasEditorRef.current?.sendAction(actionType)}
                onClose={() => setActiveTab(null)}
              />
            )}

            {activeTab === 'media' && (
              <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full shrink-0 shadow-2xl">
                <MediaLibraryPanel
                  projectId={project.id}
                  onInsertImage={(imgTag) => {
                    const updated = (activeScreen.html_content || '').trim() + '\n\n' + imgTag;
                    handleApplyAiPatch(updated);
                  }}
                  onNotify={onNotify}
                  onRefreshScreens={() => {
                    fetch(`/api/projects/${project.id}/screens`)
                      .then((r) => (r.ok ? r.json() : []))
                      .then((list: any[]) => {
                        if (Array.isArray(list) && list.length > 0) {
                          setScreens(list.map((sc) => ({ ...sc, is_main: sc.is_entry ?? sc.is_main })));
                        }
                      })
                      .catch(console.error);
                  }}
                />
              </div>
            )}

            {activeTab === 'layers' && (
              <LayersPanel
                htmlContent={activeScreen.html_content}
                selectedMbId={selectedElement?.mbId}
                onSelectMbId={(mbId) => canvasEditorRef.current?.selectByMbId?.(mbId)}
                onToggleVisibility={(mbId) => canvasEditorRef.current?.toggleElementVisibility?.(mbId)}
                onDuplicate={() => canvasEditorRef.current?.sendAction?.('MOCKBIRD_DUPLICATE')}
                onDelete={() => canvasEditorRef.current?.sendAction?.('MOCKBIRD_DELETE')}
              />
            )}

            {activeTab === 'blocks' && (
              <ComponentsCatalogPanel onInsertComponent={handleInsertBlock} />
            )}

            {activeTab === 'comments' && (
              <CommentsPanel
                screenId={activeScreen.id}
                refreshKey={commentsRefresh}
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
                  lightTokens={allTokens.light}
                  darkTokens={allTokens.dark}
                  currentTheme={tokenTheme}
                  onThemeChange={(th) => {
                    setTokenTheme(th);
                    const active = th === 'light' ? allTokens.light : allTokens.dark;
                    setTokens({ ...allTokens.shared, ...active });
                  }}
                  onTokensUpdate={(updated) => {
                    setTokens((prev) => ({ ...prev, ...updated }));
                    setAllTokens((prev) => ({
                      ...prev,
                      [tokenTheme]: { ...prev[tokenTheme], ...updated },
                    }));
                  }}
                  onSave={async (light, dark) => {
                    await fetch(`/api/tokens/${project.id}`, {
                      method: 'PUT',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        light_tokens: light,
                        dark_tokens: dark,
                        shared_tokens: allTokens.shared,
                        light_theme: light,
                        dark_theme: dark,
                      }),
                    });
                    setAllTokens((prev) => ({ ...prev, light, dark }));
                    onNotify?.('Design Tokens salvos com sucesso!');
                  }}
                />
              </div>
            )}

            {activeTab === 'history' && activeScreen && (
              <div className="w-80 border-l border-mockbird-border bg-mockbird-surface flex flex-col h-full shrink-0 shadow-2xl">
                <HistoryPanel
                  screenId={activeScreen.id}
                  onRevertSuccess={(revertedScreen) => {
                    history.markExternal(revertedScreen.html_content);
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
                  onApplyScenario={(data) => {
                    canvasEditorRef.current?.applyScenario?.(data);
                  }}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {sharePanelOpen && (
        <SharePanel
          projectId={project.id}
          projectName={projectName}
          onClose={() => setSharePanelOpen(false)}
        />
      )}
    </div>
  );
};
