import React, { useState } from 'react';
import { ShieldCheck, AlertCircle, CheckCircle2, UserPlus } from 'lucide-react';
import { withBasePath } from '../lib/basePath';

export const AcceptInvitePage: React.FC = () => {
  const token = new URLSearchParams(window.location.search).get('token') || '';
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError('A senha precisa ter ao menos 8 caracteres.');
      return;
    }
    if (password !== confirm) {
      setError('As senhas não coincidem.');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/org/members/accept-invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password, name: name.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Convite inválido ou expirado.');
      setDone(true);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-mockbird-bg text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8">
          <div className="w-7 h-7 rounded-md bg-mockbird-blue flex items-center justify-center text-white font-bold text-sm">M</div>
          <span className="font-semibold text-[15px] tracking-tight text-white">Mockbird</span>
        </div>

        <div className="flex items-center gap-2 text-mockbird-cyan text-xs font-semibold uppercase tracking-wide">
          <UserPlus size={14} /> Convite de equipe
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-white mt-2">Aceitar convite</h1>
        <p className="text-sm text-slate-400 mt-1.5">Defina seu nome e senha para entrar na organização.</p>

        {error && (
          <div className="mt-5 bg-rose-500/10 border border-rose-500/30 text-rose-300 px-3.5 py-2.5 rounded-md text-xs flex items-start gap-2.5" role="alert">
            <AlertCircle size={15} className="shrink-0 mt-px" />
            <span>{error}</span>
          </div>
        )}

        {!token && !done && (
          <div className="mt-5 bg-amber-500/10 border border-amber-500/30 text-amber-300 px-3.5 py-2.5 rounded-md text-xs">
            Link sem token. Peça um novo convite ao administrador.
          </div>
        )}

        {done ? (
          <div className="mt-6 space-y-4">
            <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3.5 py-2.5 rounded-md text-xs flex items-start gap-2.5">
              <CheckCircle2 size={15} className="shrink-0 mt-px" />
              <span>Convite aceito. Sua conta está pronta.</span>
            </div>
            <a href={withBasePath('/')} className="mb-btn-primary w-full !py-2.5 !text-sm flex items-center justify-center">Entrar no Mockbird</a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="name" className="mb-label">Seu nome (opcional)</label>
              <input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Carlos Eduardo" className="mb-input" autoComplete="name" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="mb-label">Senha</label>
              <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className="mb-input" autoComplete="new-password" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="confirm" className="mb-label">Confirmar senha</label>
              <input id="confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="••••••••" className="mb-input" autoComplete="new-password" />
            </div>
            <button type="submit" disabled={loading || !token} className="mb-btn-primary w-full !py-2.5 !text-sm">
              {loading ? 'Aceitando…' : 'Aceitar convite'}
            </button>
          </form>
        )}

        <div className="flex items-center gap-2 text-xs text-slate-500 mt-8">
          <ShieldCheck size={14} />
          <span>Convites expiram em 48 horas</span>
        </div>
      </div>
    </div>
  );
};
