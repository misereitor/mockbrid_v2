import React, { useState } from 'react';
import { ShieldCheck, AlertCircle } from 'lucide-react';

interface LoginPageProps {
  onLoginSuccess: (user: any) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);

    const endpoint = mode === 'login'
      ? '/api/auth/login'
      : mode === 'register'
        ? '/api/auth/register'
        : '/api/auth/forgot-password';
    const payload = mode === 'login'
      ? { email, password }
      : mode === 'register'
        ? { email, password, name: fullName, organization_name: orgName }
        : { email };

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Ocorreu uma falha na autenticação.');
      }

      if (mode === 'forgot') {
        setInfo(data.message || 'Se este e-mail estiver cadastrado, enviaremos as instruções em instantes.');
        return;
      }

      onLoginSuccess(data.user ?? data);
    } catch (err: any) {
      setError(err.message || 'Erro de comunicação com o servidor de autenticação.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full grid lg:grid-cols-[minmax(420px,520px)_1fr] bg-mockbird-bg text-slate-100">
      {/* Coluna do formulário */}
      <div className="flex flex-col justify-between p-8 sm:p-12">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-mockbird-blue flex items-center justify-center text-white font-bold text-sm">M</div>
          <span className="font-semibold text-[15px] tracking-tight text-white">Mockbird</span>
        </div>

        <div className="w-full max-w-sm mx-auto py-10">
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            {mode === 'login' ? 'Bem-vindo de volta' : mode === 'register' ? 'Crie sua organização' : 'Recuperar acesso'}
          </h1>
          <p className="text-sm text-slate-400 mt-1.5">
            {mode === 'login'
              ? 'Entre para continuar seus projetos e protótipos.'
              : mode === 'register'
                ? 'Comece a desenhar com sua equipe em poucos segundos.'
                : 'Informe seu e-mail e enviaremos um link para criar uma nova senha.'}
          </p>

          {info && (
            <div className="mt-5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3.5 py-2.5 rounded-md text-xs flex items-start gap-2.5" role="status">
              <ShieldCheck size={15} className="shrink-0 mt-px text-emerald-400" />
              <span>{info}</span>
            </div>
          )}

          {error && (
            <div className="mt-5 bg-rose-500/10 border border-rose-500/30 text-rose-300 px-3.5 py-2.5 rounded-md text-xs flex items-start gap-2.5" role="alert">
              <AlertCircle size={15} className="shrink-0 mt-px text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            {mode === 'register' && (
              <>
                <div className="space-y-1.5">
                  <label htmlFor="name" className="mb-label">Seu nome</label>
                  <input id="name" type="text" required value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Carlos Eduardo" className="mb-input" />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="org" className="mb-label">Nome da organização</label>
                  <input id="org" type="text" required value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Minha Startup" className="mb-input" />
                </div>
              </>
            )}
            <div className="space-y-1.5">
              <label htmlFor="email" className="mb-label">E-mail</label>
              <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@empresa.com" className="mb-input" />
            </div>
            {mode !== 'forgot' && (
              <div className="space-y-1.5">
                <label htmlFor="password" className="mb-label">Senha</label>
                <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className="mb-input" />
              </div>
            )}
            {mode === 'login' && (
              <div className="flex justify-end -mt-1">
                <button
                  type="button"
                  onClick={() => { setMode('forgot'); setError(null); setInfo(null); }}
                  className="text-xs text-slate-400 hover:text-mockbird-cyan transition-colors"
                >
                  Esqueci minha senha
                </button>
              </div>
            )}
            <button type="submit" disabled={loading} className="mb-btn-primary w-full !py-2.5 !text-sm">
              {loading ? 'Processando…' : mode === 'login' ? 'Entrar' : mode === 'register' ? 'Criar conta' : 'Enviar link de redefinição'}
            </button>
          </form>

          <p className="mt-6 text-sm text-slate-400 text-center">
            {mode === 'login' ? 'Ainda não tem conta?' : mode === 'register' ? 'Já tem uma conta?' : 'Lembrou a senha?'}{' '}
            <button
              type="button"
              onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); setInfo(null); }}
              className="text-mockbird-cyan hover:text-white font-medium transition-colors"
            >
              {mode === 'login' ? 'Criar conta' : 'Entrar'}
            </button>
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-500">
          <ShieldCheck size={14} />
          <span>Isolamento por organização · sessão protegida por cookie HTTP-Only</span>
        </div>
      </div>

      {/* Painel de produto */}
      <div className="hidden lg:flex relative overflow-hidden border-l border-mockbird-border bg-mockbird-surface items-center justify-center p-12">
        <div className="absolute inset-0 opacity-60" style={{ backgroundImage: 'radial-gradient(circle, #27272a 1px, transparent 1px)', backgroundSize: '22px 22px' }} />
        <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-mockbird-blue/20 blur-3xl" />
        <div className="relative w-full max-w-lg space-y-8">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white leading-tight">Do prompt ao protótipo,<br />no mesmo lugar.</h2>
            <p className="mt-3 text-slate-400 text-sm leading-relaxed">Descreva a tela, acompanhe o raciocínio da IA em tempo real, ajuste visualmente e apresente para o time.</p>
          </div>
          <div className="rounded-xl border border-mockbird-border bg-mockbird-bg/80 shadow-panel overflow-hidden">
            <div className="flex items-center gap-1.5 px-3 py-2 border-b border-mockbird-border">
              <span className="w-2.5 h-2.5 rounded-full bg-slate-700" /><span className="w-2.5 h-2.5 rounded-full bg-slate-700" /><span className="w-2.5 h-2.5 rounded-full bg-slate-700" />
              <span className="ml-3 text-[10px] font-mono text-slate-500">editor / checkout</span>
            </div>
            <div className="grid grid-cols-[1fr_150px] h-48">
              <div className="p-4 space-y-2.5">
                <div className="h-3 w-1/3 rounded bg-slate-700" />
                <div className="h-20 rounded-md bg-mockbird-card border border-mockbird-border" />
                <div className="h-3 w-2/3 rounded bg-slate-800" />
                <div className="h-7 w-24 rounded-md bg-mockbird-blue" />
              </div>
              <div className="border-l border-mockbird-border p-3 space-y-2 bg-mockbird-surface">
                <div className="text-[10px] font-medium text-mockbird-cyan">IA · pensando…</div>
                <div className="h-2 rounded bg-slate-800" /><div className="h-2 w-5/6 rounded bg-slate-800" /><div className="h-2 w-4/6 rounded bg-slate-800" />
              </div>
            </div>
          </div>
          <ul className="grid grid-cols-2 gap-3 text-xs text-slate-400">
            {['IA com raciocínio em stream', 'Design tokens e temas', 'Equipes e permissões', 'Modo apresentação por link'].map((t) => (
              <li key={t} className="flex items-center gap-2"><span className="w-1 h-1 rounded-full bg-mockbird-blue" />{t}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};
