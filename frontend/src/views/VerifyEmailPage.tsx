import React, { useEffect, useState } from 'react';
import { ShieldCheck, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';

export const VerifyEmailPage: React.FC = () => {
  const token = new URLSearchParams(window.location.search).get('token') || '';
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setState('error');
      setMessage('Link sem token de verificação.');
      return;
    }
    (async () => {
      try {
        const res = await fetch('/api/auth/verify-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Link inválido ou expirado.');
        setState('ok');
        setMessage(data.message || 'E-mail confirmado.');
      } catch (err: any) {
        setState('error');
        setMessage(err.message);
      }
    })();
  }, [token]);

  return (
    <div className="min-h-screen bg-mockbird-bg text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-sm text-center">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <div className="w-7 h-7 rounded-md bg-mockbird-blue flex items-center justify-center text-white font-bold text-sm">M</div>
          <span className="font-semibold text-[15px] tracking-tight text-white">Mockbird</span>
        </div>

        {state === 'loading' && (
          <div className="flex flex-col items-center gap-3 text-sm text-slate-400">
            <Loader2 size={22} className="animate-spin text-mockbird-cyan" />
            Confirmando seu e-mail…
          </div>
        )}

        {state === 'ok' && (
          <>
            <CheckCircle2 size={32} className="text-emerald-400 mx-auto" />
            <h1 className="text-xl font-semibold text-white mt-4">E-mail confirmado</h1>
            <p className="text-sm text-slate-400 mt-1.5">{message}</p>
            <a href="/" className="mb-btn-primary w-full !py-2.5 !text-sm flex items-center justify-center mt-6">Ir para o Mockbird</a>
          </>
        )}

        {state === 'error' && (
          <>
            <AlertCircle size={32} className="text-rose-400 mx-auto" />
            <h1 className="text-xl font-semibold text-white mt-4">Não foi possível confirmar</h1>
            <p className="text-sm text-slate-400 mt-1.5">{message}</p>
            <p className="text-xs text-slate-500 mt-4">Entre no app e peça um novo link na faixa de verificação.</p>
            <a href="/" className="mb-btn-primary w-full !py-2.5 !text-sm flex items-center justify-center mt-6">Voltar ao login</a>
          </>
        )}

        <div className="flex items-center gap-2 text-xs text-slate-500 mt-8 justify-center">
          <ShieldCheck size={14} />
          <span>Verificação de e-mail</span>
        </div>
      </div>
    </div>
  );
};
