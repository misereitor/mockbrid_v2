import React, { useState } from 'react';
import { Layers, Lock, Mail, User as UserIcon, ArrowRight } from 'lucide-react';

interface AuthModalProps {
  onSuccess: (user: any) => void;
}

export function AuthModal({ onSuccess }: AuthModalProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [orgName, setOrgName] = useState('Minha Organização');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login';
    const body = isRegister 
      ? { name, email, password, organization_name: orgName }
      : { email, password };

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Falha na autenticação');
      }

      const user = await res.json();
      onSuccess(user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-8 shadow-panel space-y-6">
        <div className="text-center space-y-2">
          <div className="h-12 w-12 rounded-xl bg-gradient-to-tr from-teal-500 to-emerald-400 flex items-center justify-center mx-auto shadow-teal-500/20">
            <Layers className="h-6 w-6 text-slate-950 stroke-[2.5]" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-white">
            {isRegister ? 'Criar Conta SaaS' : 'Acessar Mockbird v2'}
          </h2>
          <p className="text-xs text-slate-400">
            {isRegister 
              ? 'Ambiente Multi-tenant: cada organização com seus membros e projetos' 
              : 'Entre com suas credenciais para gerenciar seus protótipos'}
          </p>
        </div>

        {error && (
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs text-center font-medium">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegister && (
            <>
              <div>
                <label className="text-xs font-semibold text-slate-300">Seu Nome</label>
                <div className="mt-1 relative flex items-center">
                  <UserIcon className="h-4 w-4 absolute left-3 text-slate-500" />
                  <input 
                    type="text" 
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="João Silva" 
                    required 
                    className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-300">Nome da Organização (Empresa/Equipe)</label>
                <input 
                  type="text" 
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Acme Corp" 
                  required 
                  className="w-full mt-1 px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
                />
              </div>
            </>
          )}

          <div>
            <label className="text-xs font-semibold text-slate-300">Endereço de E-mail</label>
            <div className="mt-1 relative flex items-center">
              <Mail className="h-4 w-4 absolute left-3 text-slate-500" />
              <input 
                type="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="voce@empresa.com" 
                required 
                className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-300">Senha</label>
            <div className="mt-1 relative flex items-center">
              <Lock className="h-4 w-4 absolute left-3 text-slate-500" />
              <input 
                type="password" 
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••" 
                required 
                className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
              />
            </div>
          </div>

          <button 
            type="submit" 
            disabled={loading}
            className="w-full py-3 rounded-xl bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white font-semibold text-xs shadow-teal-600/20 transition flex items-center justify-center gap-2"
          >
            {loading ? 'Processando...' : (isRegister ? 'Criar Conta e Iniciar' : 'Entrar no Sistema')}
            <ArrowRight className="h-4 w-4" />
          </button>
        </form>

        <div className="text-center pt-2 border-t border-slate-800/80">
          <button 
            onClick={() => { setIsRegister(!isRegister); setError(null); }}
            className="text-xs text-teal-400 hover:underline font-medium"
          >
            {isRegister ? 'Já possui uma conta? Faça Login' : 'Ainda não tem conta? Cadastre-se'}
          </button>
        </div>
      </div>
    </div>
  );
}
