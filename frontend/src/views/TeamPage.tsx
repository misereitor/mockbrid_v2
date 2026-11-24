import React, { useState, useEffect } from 'react';
import { 
  Users, 
  UserPlus, 
  Mail, 
  AlertCircle,
  CheckCircle2,
  Shield,
  Search,
  User as UserIcon
} from 'lucide-react';
import { withBasePath } from '../lib/basePath';

interface Member {
  id: string;
  email: string;
  name?: string;
  role: string;
  is_active?: boolean;
  created_at?: string;
}

interface TeamPageProps {
  currentUserRole?: string;
}

const ROLE_LABELS: Record<string, { label: string; desc: string; badge: string }> = {
  owner: { label: 'Proprietário', desc: 'Acesso total à organização', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  admin: { label: 'Admin', desc: 'Gerencia projetos e equipe', badge: 'bg-mockbird-blue/15 text-mockbird-cyan border-mockbird-blue/30' },
  editor: { label: 'Editor', desc: 'Cria e altera protótipos', badge: 'bg-slate-800 text-slate-300 border-slate-700' },
  viewer: { label: 'Visualizador', desc: 'Apenas visualiza e comenta', badge: 'bg-slate-900 text-slate-400 border-slate-800' },
};

export const TeamPage: React.FC<TeamPageProps> = () => {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState('editor');
  const [inviting, setInviting] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);

  const loadMembers = async () => {
    try {
      const res = await fetch('/api/org/members');
      if (res.ok) {
        const data = await res.json();
        setMembers(data);
      }
    } catch (e) {
      console.error('Erro ao carregar membros:', e);
    }
  };

  useEffect(() => {
    loadMembers();
  }, []);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setInviting(true);
    setMsg(null);

    try {
      const res = await fetch('/api/org/members/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          email: email.trim(), 
          name: name.trim() || undefined,
          role 
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Falha ao convidar colaborador.');
      }
      // O backend tenta enviar por e-mail; se o transporte não estiver pronto,
      // o admin ainda recebe o link para repassar manualmente.
      const link = data.invite_url ? `${window.location.origin}${withBasePath(data.invite_url)}` : null;
      setInviteLink(data.email_sent ? null : link);
      setMsg({
        type: 'ok',
        text: data.email_sent
          ? `Convite enviado por e-mail para ${email}.`
          : `Convite criado para ${email}. Envie o link abaixo (e-mail não configurado).`,
      });
      setEmail('');
      setName('');
      loadMembers();
      setTimeout(() => setMsg(null), 8000);
    } catch (err: any) {
      setMsg({ type: 'err', text: err.message || 'Falha na requisição.' });
    } finally {
      setInviting(false);
    }
  };

  const filteredMembers = members.filter(m => 
    (m.name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    m.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    m.role.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 w-full max-w-5xl mx-auto px-8 py-10 flex flex-col gap-8">
      
      {/* Cabeçalho */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white flex items-center gap-2.5">
            <Users size={22} className="text-mockbird-cyan" />
            Membros da Equipe
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Gerencie os usuários e permissões de acesso ao workspace da sua organização.
          </p>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-mockbird-surface border border-mockbird-border text-xs text-slate-400">
          <span>Total de colaboradores:</span>
          <span className="font-semibold text-white tabular-nums">{members.length}</span>
        </div>
      </div>

      {/* Card de Convite */}
      <div className="mb-panel p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <UserPlus size={16} className="text-mockbird-cyan" />
            Convidar Novo Membro
          </h2>
          <span className="text-[11px] text-slate-500">O convidado define a própria senha</span>
        </div>

        {msg && (
          <div
            className={`p-3 rounded-lg border text-xs flex items-center gap-2.5 ${
              msg.type === 'ok'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
            }`}
          >
            {msg.type === 'ok' ? (
              <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
            ) : (
              <AlertCircle size={15} className="text-rose-400 shrink-0" />
            )}
            <span>{msg.text}</span>
          </div>
        )}

        {inviteLink && (
          <div className="flex items-center gap-2">
            <input readOnly value={inviteLink} className="mb-input !py-1.5 !text-[11px] flex-1" onFocus={(e) => e.currentTarget.select()} />
            <button
              type="button"
              onClick={() => navigator.clipboard?.writeText(inviteLink)}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-mockbird-border text-slate-300 hover:text-white"
            >
              Copiar
            </button>
          </div>
        )}

        <form onSubmit={handleInvite} className="grid grid-cols-1 sm:grid-cols-12 gap-3">
          <div className="sm:col-span-4 relative">
            <UserIcon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Nome (opcional)"
              className="mb-input !pl-8.5 !py-1.5 !text-xs"
            />
          </div>

          <div className="sm:col-span-4 relative">
            <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="colega@empresa.com"
              className="mb-input !pl-8.5 !py-1.5 !text-xs"
            />
          </div>

          <div className="sm:col-span-2">
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full rounded-md bg-mockbird-bg border border-mockbird-border px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-mockbird-blue"
            >
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
              <option value="viewer">Visualizador</option>
            </select>
          </div>

          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={inviting || !email.trim()}
              className="mb-btn-primary w-full !py-1.5 !text-xs"
            >
              {inviting ? 'Enviando…' : 'Convidar'}
            </button>
          </div>
        </form>
      </div>

      {/* Lista de Membros */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="relative max-w-xs w-full">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filtrar por nome ou e-mail…"
              className="mb-input !pl-9 !py-1.5 !text-xs"
            />
          </div>

          <div className="text-xs text-slate-500 flex items-center gap-1.5">
            <Shield size={13} />
            <span>Papéis sincronizados com RBAC</span>
          </div>
        </div>

        <div className="mb-panel overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-mockbird-border bg-mockbird-surface/80 text-slate-400 text-[11px] font-medium">
                <th className="py-2.5 px-4">Colaborador</th>
                <th className="py-2.5 px-4">E-mail</th>
                <th className="py-2.5 px-4">Papel</th>
                <th className="py-2.5 px-4 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-mockbird-border">
              {filteredMembers.map((m) => {
                const roleConfig = ROLE_LABELS[m.role] || { label: m.role, desc: '', badge: 'bg-slate-800 text-slate-300' };
                const initials = (m.name || m.email || 'U')[0].toUpperCase();

                return (
                  <tr key={m.id} className="hover:bg-mockbird-card/40 transition-colors">
                    <td className="py-3 px-4 flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-full bg-mockbird-card border border-mockbird-border flex items-center justify-center font-semibold text-xs text-slate-200 shrink-0">
                        {initials}
                      </div>
                      <div className="min-w-0">
                        <span className="font-medium text-slate-200 block truncate">
                          {m.name || m.email.split('@')[0]}
                        </span>
                      </div>
                    </td>

                    <td className="py-3 px-4 font-mono text-slate-400 text-[11px]">
                      {m.email}
                    </td>

                    <td className="py-3 px-4">
                      <span className={`inline-block px-2 py-0.5 rounded-full border text-[10px] font-medium ${roleConfig.badge}`}>
                        {roleConfig.label}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-right">
                      <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                        Ativo
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
