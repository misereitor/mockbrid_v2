import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { LoginPage } from './views/LoginPage';
import { DashboardPage, ProjectSummary } from './views/DashboardPage';
import { EditorPage } from './views/EditorPage';
import { TeamPage } from './views/TeamPage';
import { SettingsPage } from './views/SettingsPage';
import { PresentationPage } from './views/PresentationPage';

type ViewMode = 'dashboard' | 'editor' | 'team' | 'settings' | 'presentation';

export function App() {
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [loadingAuth, setLoadingAuth] = useState(true);
  const [currentView, setCurrentView] = useState<ViewMode>('dashboard');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [directProject, setDirectProject] = useState<any>(null);
  const [presentationSlug, setPresentationSlug] = useState<string | null>(null);
  const [memberCount, setMemberCount] = useState(1);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Parseador de URL para rotas reais no navegador
  const parseRouteFromUrl = useCallback(() => {
    const path = window.location.pathname;

    // Rota pública de apresentação: /p/:slug
    if (path.startsWith('/p/')) {
      const slug = path.replace('/p/', '').split('/')[0];
      if (slug) {
        setPresentationSlug(slug);
        setCurrentView('presentation');
        return;
      }
    }

    // Rota do Editor: /editor/:projectId ou /project/:projectId
    if (path.startsWith('/editor/') || path.startsWith('/project/')) {
      const parts = path.split('/').filter(Boolean);
      const projId = parts[1];
      if (projId) {
        setActiveProjectId(projId);
        try { localStorage.setItem('mockbird_last_project_id', projId); } catch {}
      }
      setCurrentView('editor');
      setSidebarCollapsed(true);
      return;
    }

    if (path === '/editor') {
      // Tenta recuperar último projeto trabalhado
      const lastId = activeProjectId || localStorage.getItem('mockbird_last_project_id');
      if (lastId) {
        setActiveProjectId(lastId);
        window.history.replaceState({}, '', `/editor/${lastId}`);
      }
      setCurrentView('editor');
      setSidebarCollapsed(true);
      return;
    }

    if (path === '/team' || path === '/equipe') {
      setCurrentView('team');
      return;
    }

    if (path === '/settings' || path === '/configuracoes' || path === '/mcp') {
      setCurrentView('settings');
      return;
    }

    // Rota padrão: Dashboard de projetos
    setCurrentView('dashboard');
  }, [activeProjectId]);

  // Navegador canônico com History API (pushState)
  const navigateTo = useCallback((url: string, replace = false) => {
    if (window.location.pathname !== url) {
      window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
    }
    parseRouteFromUrl();
  }, [parseRouteFromUrl]);

  // Listener do botão Voltar/Avançar do navegador
  useEffect(() => {
    parseRouteFromUrl();
    const handlePopState = () => parseRouteFromUrl();
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [parseRouteFromUrl]);

  // Recolhe automaticamente a sidebar no editor
  useEffect(() => {
    if (currentView === 'editor') {
      setSidebarCollapsed(true);
    }
  }, [currentView]);

  // Verifica autenticação
  const checkAuth = async () => {
    try {
      const res = await fetch('/api/auth/me');
      if (res.ok) {
        const user = await res.json();
        setCurrentUser(user);
        loadProjects();
        loadMembersCount();
      } else {
        setCurrentUser(null);
      }
    } catch (e) {
      console.error('Erro de autenticação:', e);
      setCurrentUser(null);
    } finally {
      setLoadingAuth(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const loadProjects = async () => {
    try {
      const res = await fetch('/api/projects');
      if (res.ok) {
        const data = await res.json();
        setProjects(data);
      }
    } catch (e) {
      console.error('Erro ao ler projetos:', e);
    }
  };

  // Se o usuário der F5 direto na URL /editor/:projectId, busca o projeto diretamente
  useEffect(() => {
    if (activeProjectId && !projects.some(p => p.id === activeProjectId)) {
      fetch(`/api/projects/${activeProjectId}`)
        .then(r => r.ok ? r.json() : null)
        .then(projData => {
          if (projData) setDirectProject(projData);
        })
        .catch(console.error);
    }
  }, [activeProjectId, projects]);

  const loadMembersCount = async () => {
    try {
      const res = await fetch('/api/org/members');
      if (res.ok) {
        const data = await res.json();
        setMemberCount(data.length);
      }
    } catch (e) {
      console.error('Erro ao ler membros:', e);
    }
  };

  const handleCreateProject = async (name: string, description: string) => {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description })
    });
    if (res.ok) {
      const newProj = await res.json();
      await loadProjects();
      setActiveProjectId(newProj.id);
      try { localStorage.setItem('mockbird_last_project_id', newProj.id); } catch {}
      navigateTo(`/editor/${newProj.id}`);
    }
  };

  const handleDeleteProject = async (id: string) => {
    try {
      const res = await fetch(`/api/projects/${id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setProjects((prev) => prev.filter((p) => p.id !== id));
        if (activeProjectId === id) {
          setActiveProjectId(null);
          try { localStorage.removeItem('mockbird_last_project_id'); } catch {}
        }
      }
    } catch (e) {
      console.error('Erro ao excluir projeto:', e);
    }
  };

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
    setCurrentUser(null);
    navigateTo('/dashboard');
  };

  const handleSidebarNavigate = (view: ViewMode) => {
    if (view === 'dashboard') {
      navigateTo('/dashboard');
    } else if (view === 'editor') {
      const targetId = activeProjectId || projects[0]?.id || localStorage.getItem('mockbird_last_project_id');
      if (targetId) {
        navigateTo(`/editor/${targetId}`);
      } else {
        navigateTo('/editor');
      }
    } else if (view === 'team') {
      navigateTo('/team');
    } else if (view === 'settings') {
      navigateTo('/settings');
    }
  };

  // Projeto atualmente em foco
  const activeProject = 
    projects.find(p => p.id === activeProjectId) || 
    (directProject?.id === activeProjectId ? directProject : null) || 
    projects[0];

  // Rota pública de apresentação (/p/:slug)
  if (currentView === 'presentation' && presentationSlug) {
    return (
      <PresentationPage
        slug={presentationSlug}
        onBackToApp={currentUser ? () => navigateTo('/dashboard') : undefined}
      />
    );
  }

  // Loading inicial
  if (loadingAuth) {
    return (
      <div className="min-h-screen bg-mockbird-bg text-slate-100 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <div className="w-5 h-5 border-2 border-mockbird-blue border-t-transparent rounded-full animate-spin"></div>
          <span>Carregando…</span>
        </div>
      </div>
    );
  }

  // Se não estiver autenticado
  if (!currentUser) {
    return (
      <LoginPage
        onLoginSuccess={(user) => {
          setCurrentUser(user);
          loadProjects();
          loadMembersCount();
          parseRouteFromUrl();
        }}
      />
    );
  }

  return (
    <div className="h-screen bg-mockbird-bg text-slate-100 flex font-sans selection:bg-mockbird-blue selection:text-white overflow-hidden">
      <Sidebar
        currentView={currentView}
        onNavigate={handleSidebarNavigate}
        user={currentUser}
        onLogout={handleLogout}
        activeProjectName={activeProject?.name}
        activeProjectSlug={activeProject?.slug}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
      />

      <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">
        {currentView === 'dashboard' && (
          <DashboardPage
            projects={projects}
            onSelectProject={(id) => {
              setActiveProjectId(id);
              try { localStorage.setItem('mockbird_last_project_id', id); } catch {}
              navigateTo(`/editor/${id}`);
            }}
            onCreateProject={handleCreateProject}
            onDeleteProject={handleDeleteProject}
            onNavigate={handleSidebarNavigate}
            memberCount={memberCount}
          />
        )}

        {currentView === 'editor' && activeProject && (
          <EditorPage
            key={activeProject.id}
            project={activeProject as any}
            onOpenPresentation={(slug) => {
              setPresentationSlug(slug);
              navigateTo(`/p/${slug}`);
            }}
          />
        )}

        {currentView === 'editor' && !activeProject && (
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
            <h2 className="text-base font-semibold text-white mb-1">Nenhum projeto encontrado</h2>
            <p className="text-xs text-slate-400 mb-4">Escolha ou crie um projeto no painel para abrir o editor.</p>
            <button
              onClick={() => navigateTo('/dashboard')}
              className="mb-btn-primary"
            >
              Ir para o Painel
            </button>
          </div>
        )}

        {currentView === 'team' && (
          <TeamPage currentUserRole={currentUser.role} />
        )}

        {currentView === 'settings' && (
          <SettingsPage />
        )}
      </main>
    </div>
  );
}

export default App;
