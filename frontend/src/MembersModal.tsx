import React, { useState, useEffect } from 'react';
import { Users, UserPlus, Check, X } from 'lucide-react';

interface Member {
  id: string;
  name: string;
  email: string;
  role: string;
  created_at: string;
}

export function MembersModal({ onClose }: { onClose: () => void }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState('editor');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const fetchMembers = async () => {
    try {
      const res = await fetch('/api/org/members');
      if (res.ok) {
        const data = await res.json();
        setMembers(data);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchMembers();
  }, []);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch('/api/org/members/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, name, role })
      });
      if (res.ok) {
        setSuccess(true);
        setEmail('');
        setName('');
        fetchMembers();
        setTimeout(() => setSuccess(false), 3000);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-xl bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-6">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-xl bg-teal-500/10 text-teal-400 border border-teal-500/20 flex items-center justify-center">
              <Users className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-bold text-base text-white">Membros da Organização</h3>
              <p className="text-xs text-slate-400">Gerencie quem tem acesso aos workspaces e projetos</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Formulário de Convite */}
        <form onSubmit={handleInvite} className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-3">
          <span className="text-xs font-semibold text-teal-400 uppercase tracking-wider flex items-center gap-1.5">
            <UserPlus className="h-3.5 w-3.5" /> Convidar Novo Membro
          </span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input 
              type="text" 
              placeholder="Nome"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
            />
            <input 
              type="email" 
              placeholder="E-mail"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
            />
            <div className="flex gap-2">
              <select 
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="flex-1 px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 focus:outline-none cursor-pointer"
              >
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
                <option value="viewer">Viewer</option>
              </select>
              <button 
                type="submit" 
                disabled={loading}
                className="px-4 py-2 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition shrink-0"
              >
                {loading ? '...' : (success ? <Check className="h-4 w-4" /> : 'Convidar')}
              </button>
            </div>
          </div>
        </form>

        {/* Lista de Membros */}
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {members.map((m) => (
            <div key={m.id} className="p-3 rounded-xl bg-slate-800/40 border border-slate-800 flex items-center justify-between text-xs">
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 rounded-full bg-slate-700 flex items-center justify-center font-bold text-slate-300">
                  {m.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <h4 className="font-semibold text-slate-200">{m.name}</h4>
                  <p className="text-[11px] text-slate-400">{m.email}</p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full bg-slate-800 text-teal-400 font-semibold border border-slate-700 capitalize text-[10px]">
                {m.role}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
