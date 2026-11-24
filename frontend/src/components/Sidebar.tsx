import React from 'react';
import {
  LayoutGrid,
  PenTool,
  Users,
  Settings,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  ExternalLink,
  Plus,
} from 'lucide-react';
import { openPresentation } from '../lib/presentation';

type View = 'dashboard' | 'editor' | 'team' | 'settings' | 'presentation';

interface SidebarProps {
  currentView: View;
  onNavigate: (view: View) => void;
  user: { email: string; name?: string; full_name?: string; role?: string } | null;
  onLogout: () => void;
  activeProjectName?: string;
  activeProjectId?: string;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNewProject?: () => void;
  onOpenActiveProject?: (id: string) => void;
}

const ROLE_LABEL: Record<string, string> = {
  owner: 'Proprietário',
  admin: 'Admin',
  member: 'Membro',
  viewer: 'Leitor',
};

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onNavigate,
  user,
  onLogout,
  activeProjectName,
  activeProjectId,
  collapsed,
  onToggleCollapsed,
  onNewProject,
  onOpenActiveProject,
}) => {
  const items: { id: View; label: string; icon: React.ElementType }[] = [
    { id: 'dashboard', label: 'Projetos', icon: LayoutGrid },
    { id: 'editor', label: 'Editor', icon: PenTool },
    { id: 'team', label: 'Equipe', icon: Users },
    { id: 'settings', label: 'Configurações', icon: Settings },
  ];

  const displayName = user?.name || user?.full_name || user?.email || 'Usuário';

  return (
    <aside
      className={`${collapsed ? 'w-14' : 'w-60'} shrink-0 h-screen bg-mockbird-surface border-r border-mockbird-border flex flex-col select-none transition-[width] duration-200 z-40`}
    >
      {/* Marca */}
      <div className={`h-12 flex items-center ${collapsed ? 'justify-center' : 'justify-between px-3.5'} border-b border-mockbird-border`}>
        <button onClick={() => onNavigate('dashboard')} className="flex items-center gap-2.5" aria-label="Ir para projetos">
          <div className="w-6 h-6 rounded-md bg-mockbird-blue flex items-center justify-center text-white font-bold text-[13px]">M</div>
          {!collapsed && <span className="font-semibold text-sm tracking-tight text-white">Mockbird</span>}
        </button>
        {!collapsed && (
          <button onClick={onToggleCollapsed} className="mb-btn-ghost !p-1" title="Recolher menu" aria-label="Recolher menu">
            <PanelLeftClose size={15} />
          </button>
        )}
      </div>

      {/* Navegação */}
      <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
        {items.map(({ id, label, icon: Icon }) => {
          const active = currentView === id;
          return (
            <div key={id} className="relative group/nav flex items-center">
              <button
                onClick={() => onNavigate(id)}
                title={collapsed ? label : undefined}
                aria-current={active ? 'page' : undefined}
                className={`w-full flex items-center ${collapsed ? 'justify-center' : 'gap-2.5 px-2.5'} py-2 rounded-md text-[13px] font-medium transition-colors duration-150 ${
                  active
                    ? 'bg-mockbird-card text-white'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-mockbird-card/60'
                }`}
              >
                <Icon size={16} className={active ? 'text-mockbird-cyan' : ''} />
                {!collapsed && <span>{label}</span>}
              </button>
              {!collapsed && id === 'editor' && onNewProject && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onNewProject();
                  }}
                  className="absolute right-2 p-1 rounded hover:bg-mockbird-surface text-slate-500 hover:text-mockbird-cyan transition-colors"
                  title="Criar novo projeto"
                  aria-label="Criar novo projeto"
                >
                  <Plus size={13} />
                </button>
              )}
            </div>
          );
        })}

        {!collapsed && activeProjectName && (
          <div className="pt-4 mt-3 border-t border-mockbird-border">
            <div className="px-2.5 text-[10px] font-medium uppercase tracking-wider text-slate-500 mb-1.5">Projeto ativo</div>
            <div className="px-2.5 py-2 rounded-md bg-mockbird-bg border border-mockbird-border">
              {activeProjectId && onOpenActiveProject ? (
                <button
                  type="button"
                  onClick={() => onOpenActiveProject(activeProjectId)}
                  className="w-full text-left text-xs font-medium text-slate-200 truncate hover:text-mockbird-cyan transition-colors block"
                  title={`Abrir editor de ${activeProjectName}`}
                >
                  {activeProjectName}
                </button>
              ) : (
                <div className="text-xs font-medium text-slate-200 truncate">{activeProjectName}</div>
              )}
              {activeProjectId && (
                <button
                  onClick={() => { openPresentation(activeProjectId).catch(() => {}); }}
                  className="mt-1 inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-mockbird-cyan transition-colors"
                  title={`Abrir apresentação de ${activeProjectName || ''}`}
                >
                  Apresentação <ExternalLink size={10} />
                </button>
              )}
            </div>
          </div>
        )}
      </nav>

      {/* Rodapé: usuário */}
      <div className="p-2 border-t border-mockbird-border space-y-1">
        {collapsed && (
          <button onClick={onToggleCollapsed} className="w-full flex justify-center py-2 mb-btn-ghost" title="Expandir menu" aria-label="Expandir menu">
            <PanelLeftOpen size={15} />
          </button>
        )}
        <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-2.5 px-1.5'} py-1.5`}>
          <div
            className="w-7 h-7 rounded-full bg-mockbird-card border border-mockbird-border flex items-center justify-center text-[11px] font-semibold text-slate-200 shrink-0"
            title={collapsed ? displayName : undefined}
          >
            {displayName[0]?.toUpperCase()}
          </div>
          {!collapsed && (
            <>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-slate-200 truncate" title={user?.email}>{displayName}</div>
                <div className="text-[10px] text-slate-500">{ROLE_LABEL[user?.role || ''] || user?.role || 'Admin'}</div>
              </div>
              <button onClick={onLogout} className="mb-btn-ghost !p-1.5 hover:!text-rose-400" title="Sair" aria-label="Sair">
                <LogOut size={14} />
              </button>
            </>
          )}
        </div>
      </div>
    </aside>
  );
};

