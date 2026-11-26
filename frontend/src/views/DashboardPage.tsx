import React, { useRef, useState, useMemo } from 'react';
import {
  Plus,
  Search,
  Copy,
  Check,
  MonitorPlay,
  Link2,
  ArrowUpRight,
  FolderPlus,
  X,
  Layers,
  Users,
  FolderKanban,
  Plug,
  Trash2,
  Upload,
  Edit2,
} from 'lucide-react';
import { openPresentation } from '../lib/presentation';
import { SharePanel } from '../components/SharePanel';

export interface ProjectPreviewScreen {
  id: string;
  name: string;
  html_content: string;
  css_content?: string;
  width?: number;
  height?: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  description: string;
  screens_count?: number;
  screens?: { id: string; name: string; slug: string; is_main?: boolean }[];
  preview_screen?: ProjectPreviewScreen | null;
  preview_tokens?: Record<string, string> | null;
  updated_at?: string;
}

function buildThumbnailSrcDoc(
  screen: ProjectPreviewScreen,
  tokens?: Record<string, string> | null
): string {
  const tokenVars = Object.entries(tokens || {})
    .map(([k, v]) => `--${k}: ${v};`)
    .join('\n');
  const rawHtml = screen.html_content || '';
  const hasFullDoc = /<!doctype\s+html|<html[\s>]/i.test(rawHtml);
  const customStyle = `<style>
    :root { ${tokenVars} }
    html, body {
      margin: 0;
      padding: 0;
      overflow: hidden !important;
      user-select: none;
      pointer-events: none;
      background: var(--color-bg, #09090b);
      color: var(--color-text, #f8fafc);
      font-family: var(--font-body, Inter, system-ui, sans-serif);
    }
    ${screen.css_content || ''}
  </style>`;

  if (hasFullDoc) {
    if (/<\/head>/i.test(rawHtml)) {
      return rawHtml.replace(/<\/head>/i, `${customStyle}</head>`);
    }
    return `${customStyle}${rawHtml}`;
  }

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.tailwindcss.com"></script>
  ${customStyle}
</head>
<body>${rawHtml}</body>
</html>`;
}

const ProjectThumbnail: React.FC<{
  screen?: ProjectPreviewScreen | null;
  tokens?: Record<string, string> | null;
}> = ({ screen, tokens }) => {
  const hasHtml = Boolean(screen?.html_content && screen.html_content.trim());
  const screenWidth = screen?.width && screen.width > 0 ? screen.width : 1440;
  const screenHeight = screen?.height && screen.height > 0 ? screen.height : 900;
  // O card no grid tem ~340px de largura; escala proporcional para caber nos 144px (h-36) de altura
  const scale = Math.min(340 / screenWidth, 144 / screenHeight, 0.35);

  const srcDoc = useMemo(() => {
    if (!hasHtml || !screen) return '';
    return buildThumbnailSrcDoc(screen, tokens);
  }, [hasHtml, screen, tokens]);

  if (!hasHtml || !screen) {
    return (
      <>
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage: 'radial-gradient(circle, #27272a 1px, transparent 1px)',
            backgroundSize: '16px 16px',
          }}
        />
        <div className="absolute left-5 top-5 right-12 space-y-2">
          <div className="h-2 w-1/3 rounded bg-slate-700" />
          <div className="h-10 rounded-md bg-mockbird-card border border-mockbird-border" />
          <div className="h-2 w-1/2 rounded bg-slate-800" />
        </div>
      </>
    );
  }

  return (
    <div className="absolute inset-0 overflow-hidden bg-mockbird-bg flex items-start justify-center">
      <div
        className="origin-top pointer-events-none select-none shrink-0"
        style={{
          width: `${screenWidth}px`,
          height: `${screenHeight}px`,
          transform: `scale(${scale})`,
          transformOrigin: 'top center',
        }}
      >
        <iframe
          title={`Preview de ${screen.name}`}
          srcDoc={srcDoc}
          sandbox="allow-same-origin allow-scripts"
          loading="lazy"
          tabIndex={-1}
          className="w-full h-full border-0 pointer-events-none"
        />
      </div>
      <div className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-black/75 via-black/30 to-transparent flex items-end justify-between px-3 pb-1.5">
        <span className="text-[10px] font-medium text-slate-200 truncate bg-black/50 backdrop-blur-sm px-2 py-0.5 rounded border border-white/10">
          {screen.name}
        </span>
      </div>
    </div>
  );
};

interface DashboardPageProps {
  projects: ProjectSummary[];
  onSelectProject: (projectId: string) => void;
  onCreateProject: (name: string, description: string) => Promise<void>;
  onImportDesign?: (file: File, name: string) => Promise<void>;
  onDeleteProject?: (projectId: string) => Promise<void> | void;
  onDuplicateProject?: (projectId: string) => Promise<void> | void;
  onRenameProject?: (projectId: string, newName: string) => Promise<void> | void;
  onNavigate: (view: 'dashboard' | 'editor' | 'team' | 'settings' | 'presentation') => void;
  memberCount: number;
}

const formatDate = (iso?: string) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
};

export const DashboardPage: React.FC<DashboardPageProps> = ({
  projects,
  onSelectProject,
  onCreateProject,
  onImportDesign,
  onDeleteProject,
  onDuplicateProject,
  onRenameProject,
  onNavigate,
  memberCount,
}) => {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectDesc, setProjectDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState('');
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [sharePanelProject, setSharePanelProject] = useState<{ id: string; name: string } | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [renaming, setRenaming] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  const handleImport = async (file?: File) => {
    if (!file || !onImportDesign) return;
    setImporting(true);
    setImportError(null);
    try {
      await onImportDesign(file, file.name.replace(/\.zip$/i, ''));
    } catch (err: any) {
      setImportError(err.message || 'Falha ao importar o corpus design/.');
    } finally {
      setImporting(false);
      if (importInputRef.current) importInputRef.current.value = '';
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectName.trim()) return;
    setCreating(true);
    try {
      await onCreateProject(projectName.trim(), projectDesc.trim());
      setProjectName('');
      setProjectDesc('');
      setShowCreateForm(false);
    } finally {
      setCreating(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q)
    );
  }, [projects, query]);

  const totalScreens = projects.reduce((acc, p) => acc + (p.screens?.length || p.screens_count || 1), 0);

  const stats = [
    { label: 'Projetos', value: projects.length, icon: FolderKanban },
    { label: 'Telas', value: totalScreens, icon: Layers },
    { label: 'Membros', value: memberCount, icon: Users },
  ];

  return (
    <div className="flex-1 w-full max-w-6xl mx-auto px-8 py-10 flex flex-col gap-8">
      {/* Cabeçalho */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Projetos</h1>
          <p className="text-sm text-slate-400 mt-1">Seus protótipos, telas e sistemas de design.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => onNavigate('settings')} className="mb-btn-outline">
            <Plug size={14} /> IA &amp; MCP
          </button>
          {onImportDesign && (
            <>
              <input
                ref={importInputRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                aria-label="Importar corpus design"
                onChange={(e) => handleImport(e.target.files?.[0])}
              />
              <button
                type="button"
                onClick={() => importInputRef.current?.click()}
                disabled={importing}
                className="mb-btn-outline"
                title="Importa um ZIP com a pasta design/ (canvas.json + telas HTML + tokens.json) do Mockbird v1"
              >
                <Upload size={14} /> {importing ? 'Importando…' : 'Importar design/'}
              </button>
            </>
          )}
          <button onClick={() => setShowCreateForm(true)} className="mb-btn-primary">
            <Plus size={14} /> Novo projeto
          </button>
        </div>
      </div>

      {/* Métricas */}
      <div className="grid grid-cols-3 gap-px rounded-xl overflow-hidden border border-mockbird-border bg-mockbird-border">
        {stats.map(({ label, value, icon: Icon }) => (
          <div key={label} className="bg-mockbird-surface px-5 py-4 flex items-center justify-between">
            <div>
              <div className="text-[11px] font-medium text-slate-400">{label}</div>
              <div className="text-2xl font-semibold text-white mt-0.5 tabular-nums">{value}</div>
            </div>
            <Icon size={18} className="text-slate-600" />
          </div>
        ))}
      </div>

      {importError && (
        <div className="mb-panel !border-red-500/40 bg-red-500/10 px-4 py-3 text-xs text-red-300 flex items-start justify-between gap-3">
          <span>{importError}</span>
          <button type="button" onClick={() => setImportError(null)} className="mb-btn-ghost !p-1" aria-label="Fechar erro">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Criação */}
      {showCreateForm && (
        <form onSubmit={handleCreate} className="mb-panel p-5 space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <FolderPlus size={16} className="text-mockbird-cyan" /> Novo projeto
            </h2>
            <button type="button" onClick={() => setShowCreateForm(false)} className="mb-btn-ghost !p-1" aria-label="Fechar">
              <X size={15} />
            </button>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="mb-label" htmlFor="proj-name">Nome</label>
              <input id="proj-name" autoFocus required value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="SaaS Financeiro" className="mb-input" />
            </div>
            <div className="space-y-1.5">
              <label className="mb-label" htmlFor="proj-desc">Descrição (opcional)</label>
              <input id="proj-desc" value={projectDesc} onChange={(e) => setProjectDesc(e.target.value)} placeholder="Checkout e dashboard para validação" className="mb-input" />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowCreateForm(false)} className="mb-btn-ghost">Cancelar</button>
            <button type="submit" disabled={creating} className="mb-btn-primary">
              {creating ? 'Criando…' : 'Criar projeto'}
            </button>
          </div>
        </form>
      )}

      {/* Busca + grade */}
      <div className="space-y-4">
        <div className="relative max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar projetos…"
            className="mb-input !pl-9 !py-1.5 !text-xs"
            aria-label="Buscar projetos"
          />
        </div>

        {projects.length === 0 ? (
          <div className="mb-panel border-dashed py-16 text-center flex flex-col items-center">
            <div className="w-11 h-11 rounded-lg bg-mockbird-card border border-mockbird-border flex items-center justify-center text-slate-400 mb-4">
              <FolderPlus size={20} />
            </div>
            <h3 className="text-sm font-semibold text-white">Nenhum projeto ainda</h3>
            <p className="text-xs text-slate-400 mt-1 max-w-sm leading-relaxed">
              Crie seu primeiro projeto para desenhar telas com IA, definir tokens e compartilhar um link de apresentação.
            </p>
            <button onClick={() => setShowCreateForm(true)} className="mb-btn-primary mt-5">
              <Plus size={14} /> Criar projeto
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-slate-500 py-10 text-center">Nenhum projeto corresponde a “{query}”.</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((proj) => {
              const screens = proj.screens || [];
              const count = screens.length || proj.screens_count || 1;
              return (
                <div
                  key={proj.id}
                  className="group mb-panel overflow-hidden hover:border-mockbird-borderlight transition-colors duration-150 flex flex-col"
                >
                  {/* Pré-visualização real da tela principal do projeto */}
                  <button
                    onClick={() => onSelectProject(proj.id)}
                    className="relative h-36 bg-mockbird-bg border-b border-mockbird-border text-left overflow-hidden"
                    aria-label={`Abrir ${proj.name}`}
                  >
                    <ProjectThumbnail screen={proj.preview_screen} tokens={proj.preview_tokens} />
                    <div className="absolute right-2.5 top-2.5 p-1 rounded-md bg-black/50 backdrop-blur-sm border border-white/10 text-slate-300 group-hover:text-mockbird-cyan group-hover:border-mockbird-cyan/40 transition-colors">
                      <ArrowUpRight size={14} />
                    </div>
                  </button>

                  <div className="p-4 flex-1 flex flex-col gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        {editingProjectId === proj.id ? (
                          <div className="flex items-center gap-1.5 w-full">
                            <input
                              type="text"
                              value={renameValue}
                              onChange={(e) => setRenameValue(e.target.value)}
                              onKeyDown={async (e) => {
                                if (e.key === 'Enter') {
                                  const val = renameValue.trim();
                                  if (val && val !== proj.name && onRenameProject) {
                                    setRenaming(true);
                                    try {
                                      await onRenameProject(proj.id, val);
                                      setEditingProjectId(null);
                                    } finally {
                                      setRenaming(false);
                                    }
                                  } else {
                                    setEditingProjectId(null);
                                  }
                                }
                                if (e.key === 'Escape') setEditingProjectId(null);
                              }}
                              autoFocus
                              disabled={renaming}
                              className="bg-mockbird-bg border border-mockbird-cyan text-white text-xs px-2 py-1 rounded outline-none w-full font-medium"
                              placeholder="Nome do projeto"
                              aria-label="Editar nome do projeto"
                            />
                            <button
                              type="button"
                              onClick={async () => {
                                const val = renameValue.trim();
                                if (val && val !== proj.name && onRenameProject) {
                                  setRenaming(true);
                                  try {
                                    await onRenameProject(proj.id, val);
                                    setEditingProjectId(null);
                                  } finally {
                                    setRenaming(false);
                                  }
                                } else {
                                  setEditingProjectId(null);
                                }
                              }}
                              className="p-1 rounded bg-mockbird-blue hover:bg-mockbird-bluedark text-white text-xs shrink-0"
                              title="Salvar nome"
                            >
                              <Check size={12} />
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingProjectId(null)}
                              className="p-1 rounded text-slate-400 hover:text-white text-xs shrink-0"
                              title="Cancelar"
                            >
                              <X size={12} />
                            </button>
                          </div>
                        ) : (
                          <>
                            <h3 className="font-medium text-sm text-white truncate" title={proj.name}>{proj.name}</h3>
                            <span className="text-[10px] text-slate-500 shrink-0 tabular-nums">{formatDate(proj.updated_at)}</span>
                          </>
                        )}
                      </div>
                      <p className="text-xs text-slate-400 line-clamp-2 mt-1 min-h-[32px] leading-relaxed">
                        {proj.description || 'Sem descrição.'}
                      </p>
                    </div>

                    <div className="flex items-center justify-between pt-3 border-t border-mockbird-border">
                      <span className="text-[11px] text-slate-500">{count} {count === 1 ? 'tela' : 'telas'}</span>
                      <div className="flex items-center gap-0.5">
                        <button
                          onClick={() => openPresentation(proj.id)}
                          className="mb-btn-ghost !p-1.5"
                          title="Pré-visualizar (só para você)"
                          aria-label="Pré-visualizar apresentação"
                        >
                          <MonitorPlay size={14} />
                        </button>
                        <button
                          onClick={() => setSharePanelProject({ id: proj.id, name: proj.name })}
                          className="mb-btn-ghost !p-1.5"
                          title="Compartilhar"
                          aria-label="Compartilhar projeto"
                        >
                          <Link2 size={14} />
                        </button>
                        {onRenameProject && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingProjectId(proj.id);
                              setRenameValue(proj.name);
                            }}
                            className="mb-btn-ghost !p-1.5 hover:!text-mockbird-cyan text-slate-500 transition-colors"
                            title="Renomear projeto"
                            aria-label="Renomear projeto"
                          >
                            <Edit2 size={14} />
                          </button>
                        )}
                        {onDuplicateProject && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDuplicateProject(proj.id);
                            }}
                            className="mb-btn-ghost !p-1.5 hover:!text-mockbird-cyan text-slate-500 transition-colors"
                            title="Duplicar projeto"
                            aria-label="Duplicar projeto"
                          >
                            <Copy size={14} />
                          </button>
                        )}
                        {onDeleteProject && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (window.confirm(`Tem certeza que deseja excluir o projeto "${proj.name}"? Todos os canvases e telas serão apagados.`)) {
                                onDeleteProject(proj.id);
                              }
                            }}
                            className="mb-btn-ghost !p-1.5 hover:!text-rose-400 hover:!bg-rose-500/10 text-slate-500 transition-colors"
                            title="Excluir projeto"
                            aria-label="Excluir projeto"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                        <button onClick={() => onSelectProject(proj.id)} className="mb-btn-outline !py-1 ml-1">
                          Abrir
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {sharePanelProject && (
        <SharePanel
          projectId={sharePanelProject.id}
          projectName={sharePanelProject.name}
          onClose={() => setSharePanelProject(null)}
        />
      )}
    </div>
  );
};
