import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { LoginPage } from './views/LoginPage';
import { DashboardPage, ProjectSummary } from './views/DashboardPage';
import { EditorPage } from './views/EditorPage';
import { TeamPage } from './views/TeamPage';
import { SettingsPage } from './views/SettingsPage';
import { PresentationPage } from './views/PresentationPage';
import { ResetPasswordPage } from './views/ResetPasswordPage';
import { VerifyEmailPage } from './views/VerifyEmailPage';
import { AcceptInvitePage } from './views/AcceptInvitePage';
import { NewProjectModal } from './components/NewProjectModal';
import { stripBasePath, withBasePath } from './lib/basePath';

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
  const [emailStatus, setEmailStatus] = useState<any>(null);
  const [resending, setResending] = useState(false);
  const [resendMsg, setResendMsg] = useState<string | null>(null);
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);

  // Parseador de URL para rotas reais no navegador (compatível com raiz e subpath /mockbrid)
  const parseRouteFromUrl = useCallback(() => {
    const path = stripBasePath(window.location.pathname);

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
      setShowNewProjectModal(true);
      setCurrentView('dashboard');
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
    const targetUrl = withBasePath(url);
    if (window.location.pathname !== targetUrl) {
      window.history[replace ? 'replaceState' : 'pushState']({}, '', targetUrl);
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
        loadEmailStatus();
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

  const loadEmailStatus = async () => {
    try {
      const res = await fetch('/api/auth/email-status');
      if (res.ok) setEmailStatus(await res.json());
    } catch (e) {
      console.error('Erro ao ler status de e-mail:', e);
    }
  };

  const handleResendVerification = async () => {
    setResending(true);
    setResendMsg(null);
    try {
      const res = await fetch('/api/auth/resend-verification', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Falha ao reenviar.');
      setResendMsg(data.status === 'already_verified' ? 'E-mail já confirmado.' : 'Link enviado. Confira sua caixa de entrada.');
    } catch (err: any) {
      setResendMsg(err.message || 'Falha ao reenviar.');
    } finally {
      setResending(false);
    }
  };

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
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Falha ao criar novo projeto.');
    }
    const newProj = await res.json();
    await loadProjects();
    setActiveProjectId(newProj.id);
    try { localStorage.setItem('mockbird_last_project_id', newProj.id); } catch {}
    navigateTo(`/editor/${newProj.id}`);
  };

  const handleImportDesign = async (file: File, name: string) => {
    const form = new FormData();
    form.append('file', file);
    if (name.trim()) form.append('name', name.trim());
    const res = await fetch('/api/projects/import/design', {
      method: 'POST',
      body: form,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(data?.detail || 'Falha ao importar o corpus design/.');
    }
    await loadProjects();
    setActiveProjectId(data.project.id);
    try { localStorage.setItem('mockbird_last_project_id', data.project.id); } catch {}
    navigateTo(`/editor/${data.project.id}`);
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

  const handleDuplicateProject = async (id: string) => {
    try {
      const res = await fetch(`/api/projects/${id}/duplicate`, { method: 'POST' });
      if (!res.ok) throw new Error('Falha ao duplicar projeto');
      const duplicated = await res.json();
      setProjects((prev) => [duplicated, ...prev]);
    } catch (e: any) {
      console.error('Erro ao duplicar projeto:', e);
      alert(e.message || 'Erro ao duplicar projeto');
    }
  };

  const handleRenameProject = async (id: string, newName: string) => {
    try {
      const res = await fetch(`/api/projects/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Falha ao renomear projeto');
      }
      const updated = await res.json();
      setProjects((prev) =>
        prev.map((p) => (p.id === id ? { ...p, name: updated.name } : p))
      );
    } catch (e: any) {
      console.error('Erro ao renomear projeto:', e);
      alert(e.message || 'Erro ao renomear projeto');
      throw e;
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
      setShowNewProjectModal(true);
    } else if (view === 'team') {
      navigateTo('/team');
    } else if (view === 'settings') {
      navigateTo('/settings');
    }
  };

  // Projeto atualmente em foco: apenas o explicitamente ativo ou buscado diretamente
  const activeProject = 
    projects.find(p => p.id === activeProjectId) || 
    (directProject?.id === activeProjectId ? directProject : null);

  // Rota pública de apresentação (/p/:slug)
  if (currentView === 'presentation' && presentationSlug) {
    return (
      <PresentationPage
        slug={presentationSlug}
        onBackToApp={currentUser ? () => {
          if (activeProjectId) {
            navigateTo('/editor');
          } else {
            navigateTo('/dashboard');
          }
        } : undefined}
      />
    );
  }

  // Páginas públicas de autenticação (funcionam com ou sem sessão)
  const publicPath = stripBasePath(window.location.pathname).replace(/\/+$/, '') || '/';
  if (publicPath === '/reset-password') return <ResetPasswordPage />;
  if (publicPath === '/verify-email') return <VerifyEmailPage />;
  if (publicPath === '/accept-invite') return <AcceptInvitePage />;

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
        activeProjectId={activeProject?.id}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
        onNewProject={() => setShowNewProjectModal(true)}
        onOpenActiveProject={(id) => {
          setActiveProjectId(id);
          try { localStorage.setItem('mockbird_last_project_id', id); } catch {}
          navigateTo(`/editor/${id}`);
        }}
      />

      <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">
        {emailStatus?.configured &&
          emailStatus.require_verification &&
          !currentUser.email_verified && (
            <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-2.5 bg-amber-500/10 border-b border-amber-500/20 text-xs text-amber-200">
              <span>Confirme seu e-mail para garantir o acesso à conta. Enviamos um link para {currentUser.email}.</span>
              <div className="flex items-center gap-3">
                {resendMsg && <span className="text-amber-100/80">{resendMsg}</span>}
                <button
                  onClick={handleResendVerification}
                  disabled={resending}
                  className="font-semibold text-amber-100 underline underline-offset-2 hover:text-white disabled:opacity-50"
                >
                  {resending ? 'Enviando…' : 'Reenviar link'}
                </button>
              </div>
            </div>
          )}

        <div key={currentView} className="flex-1 min-h-0 flex flex-col animate-in fade-in duration-150">
          {currentView === 'dashboard' && (
            <DashboardPage
              projects={projects}
              onSelectProject={(id) => {
                setActiveProjectId(id);
                try { localStorage.setItem('mockbird_last_project_id', id); } catch {}
                navigateTo(`/editor/${id}`);
              }}
              onCreateProject={handleCreateProject}
              onImportDesign={handleImportDesign}
              onDeleteProject={handleDeleteProject}
              onDuplicateProject={handleDuplicateProject}
              onRenameProject={handleRenameProject}
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
              onNewProject={() => setShowNewProjectModal(true)}
              onRenameProject={handleRenameProject}
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
            <SettingsPage currentUser={currentUser} />
          )}
        </div>
      </main>

      <NewProjectModal
        isOpen={showNewProjectModal}
        onClose={() => setShowNewProjectModal(false)}
        onCreateProject={handleCreateProject}
        recentProject={activeProject ? { id: activeProject.id, name: activeProject.name } : null}
        onContinueRecent={(id) => {
          setActiveProjectId(id);
          try { localStorage.setItem('mockbird_last_project_id', id); } catch {}
          navigateTo(`/editor/${id}`);
        }}
      />
    </div>
  );
}

export default App;
