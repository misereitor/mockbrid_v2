import React, { useEffect, useState } from 'react';
import {
  Mail,
  Send,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Lock,
  Server,
} from 'lucide-react';

interface EmailSettings {
  provider: 'disabled' | 'smtp' | 'resend';
  from_email: string;
  from_name: string;
  reply_to: string;
  app_base_url: string;
  require_verification: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_security: 'starttls' | 'ssl' | 'none';
  has_smtp_password: boolean;
  has_resend_api_key: boolean;
  configured: boolean;
  updated_at?: string;
}

const EMPTY: EmailSettings = {
  provider: 'disabled',
  from_email: '',
  from_name: 'Mockbird',
  reply_to: '',
  app_base_url: '',
  require_verification: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_security: 'starttls',
  has_smtp_password: false,
  has_resend_api_key: false,
  configured: false,
};

export const EmailSettingsPanel: React.FC = () => {
  const [form, setForm] = useState<EmailSettings>(EMPTY);
  const [smtpPassword, setSmtpPassword] = useState('');
  const [resendKey, setResendKey] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const set = <K extends keyof EmailSettings>(key: K, value: EmailSettings[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/admin/email-settings');
        const data = await res.json();
        if (res.ok) setForm({ ...EMPTY, ...data });
        else setFeedback({ type: 'err', text: data.detail || 'Falha ao carregar configurações.' });
      } catch {
        setFeedback({ type: 'err', text: 'Erro de comunicação com o servidor.' });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFeedback(null);
    try {
      const res = await fetch('/api/admin/email-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          smtp_password: smtpPassword || null,
          resend_api_key: resendKey || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Falha ao salvar.');
      setForm({ ...EMPTY, ...data });
      setSmtpPassword('');
      setResendKey('');
      setFeedback({ type: 'ok', text: 'Configurações salvas.' });
    } catch (err: any) {
      setFeedback({ type: 'err', text: err.message || 'Falha ao salvar.' });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setFeedback(null);
    try {
      const res = await fetch('/api/admin/email-settings/test', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Falha no envio de teste.');
      setFeedback({ type: 'ok', text: `E-mail de teste enviado para ${data.to}.` });
    } catch (err: any) {
      setFeedback({ type: 'err', text: err.message || 'Falha no envio de teste.' });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Loader2 size={16} className="animate-spin" /> Carregando configurações de e-mail…
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="bg-mockbird-card border border-mockbird-border rounded-2xl p-6 shadow-xl space-y-6">
      <div className="flex items-center justify-between pb-4 border-b border-mockbird-border gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <Mail size={18} className="text-mockbird-cyan" />
            Envio de e-mail transacional
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Usado para redefinição de senha, verificação de conta e convites de equipe.
          </p>
        </div>
        <span
          className={`shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-full border ${
            form.configured
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
              : 'bg-amber-500/10 text-amber-300 border-amber-500/20'
          }`}
        >
          {form.configured ? 'Configurado' : 'Pendente'}
        </span>
      </div>

      {feedback && (
        <div
          className={`p-3 rounded-lg border text-xs flex items-start gap-2.5 ${
            feedback.type === 'ok'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
          }`}
        >
          {feedback.type === 'ok' ? <CheckCircle2 size={15} className="shrink-0 mt-px" /> : <AlertCircle size={15} className="shrink-0 mt-px" />}
          <span>{feedback.text}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="mb-label">Transporte</label>
          <select
            value={form.provider}
            onChange={(e) => set('provider', e.target.value as EmailSettings['provider'])}
            className="mb-input"
          >
            <option value="disabled">Desativado</option>
            <option value="smtp">SMTP (Gmail, SES, Postmark, Mailgun…)</option>
            <option value="resend">Resend (API HTTP)</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="mb-label">URL pública do app</label>
          <input
            value={form.app_base_url}
            onChange={(e) => set('app_base_url', e.target.value)}
            placeholder="https://app.suaempresa.com"
            className="mb-input"
          />
          <p className="text-[11px] text-slate-500">Base dos links enviados por e-mail.</p>
        </div>
        <div className="space-y-1.5">
          <label className="mb-label">E-mail remetente</label>
          <input
            type="email"
            value={form.from_email}
            onChange={(e) => set('from_email', e.target.value)}
            placeholder="nao-responda@suaempresa.com"
            className="mb-input"
          />
        </div>
        <div className="space-y-1.5">
          <label className="mb-label">Nome remetente</label>
          <input
            value={form.from_name}
            onChange={(e) => set('from_name', e.target.value)}
            placeholder="Mockbird"
            className="mb-input"
          />
        </div>
        <div className="space-y-1.5">
          <label className="mb-label">Responder para (opcional)</label>
          <input
            type="email"
            value={form.reply_to}
            onChange={(e) => set('reply_to', e.target.value)}
            placeholder="suporte@suaempresa.com"
            className="mb-input"
          />
        </div>
        <label className="flex items-start gap-2.5 pt-6 cursor-pointer">
          <input
            type="checkbox"
            checked={form.require_verification}
            onChange={(e) => set('require_verification', e.target.checked)}
            className="mt-0.5 accent-mockbird-blue"
          />
          <span className="text-xs text-slate-300">
            Exigir confirmação de e-mail no cadastro
            <span className="block text-[11px] text-slate-500">
              Mostra um aviso no app até o usuário confirmar (não bloqueia o login).
            </span>
          </span>
        </label>
      </div>

      {form.provider === 'smtp' && (
        <div className="border-t border-mockbird-border pt-5 space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Server size={15} className="text-mockbird-cyan" /> Servidor SMTP
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="mb-label">Host</label>
              <input
                value={form.smtp_host}
                onChange={(e) => set('smtp_host', e.target.value)}
                placeholder="smtp.suaempresa.com"
                className="mb-input"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="mb-label">Porta</label>
                <input
                  type="number"
                  value={form.smtp_port}
                  onChange={(e) => set('smtp_port', Number(e.target.value) || 587)}
                  className="mb-input"
                />
              </div>
              <div className="space-y-1.5">
                <label className="mb-label">Segurança</label>
                <select
                  value={form.smtp_security}
                  onChange={(e) => set('smtp_security', e.target.value as EmailSettings['smtp_security'])}
                  className="mb-input"
                >
                  <option value="starttls">STARTTLS</option>
                  <option value="ssl">SSL/TLS</option>
                  <option value="none">Nenhuma</option>
                </select>
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="mb-label">Usuário</label>
              <input
                value={form.smtp_username}
                onChange={(e) => set('smtp_username', e.target.value)}
                placeholder="nao-responda@suaempresa.com"
                className="mb-input"
              />
            </div>
            <div className="space-y-1.5">
              <label className="mb-label flex items-center gap-1.5">
                <Lock size={12} /> Senha / App password
              </label>
              <input
                type="password"
                value={smtpPassword}
                onChange={(e) => setSmtpPassword(e.target.value)}
                placeholder={form.has_smtp_password ? '•••••••• (salva — deixe vazio para manter)' : 'Senha do SMTP'}
                className="mb-input"
                autoComplete="new-password"
              />
            </div>
          </div>
        </div>
      )}

      {form.provider === 'resend' && (
        <div className="border-t border-mockbird-border pt-5 space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <KeyIcon /> API Key da Resend
          </div>
          <input
            type="password"
            value={resendKey}
            onChange={(e) => setResendKey(e.target.value)}
            placeholder={form.has_resend_api_key ? '•••••••• (salva — deixe vazio para manter)' : 're_...'}
            className="mb-input"
            autoComplete="new-password"
          />
          <p className="text-[11px] text-slate-500">
            Crie a chave em resend.com/api-keys e verifique o domínio remetente na Resend.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-mockbird-border pt-5">
        <button type="submit" disabled={saving} className="mb-btn-primary !py-2 !text-xs">
          {saving ? 'Salvando…' : 'Salvar configurações'}
        </button>
        <button
          type="button"
          onClick={handleTest}
          disabled={testing || !form.configured}
          className="px-4 py-2 rounded-lg text-xs font-semibold border border-mockbird-border text-slate-300 hover:text-white hover:border-mockbird-blue transition-colors disabled:opacity-40 flex items-center gap-2"
        >
          {testing ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
          Enviar e-mail de teste
        </button>
        <span className="text-[11px] text-slate-500">
          O teste vai para o seu próprio endereço.
        </span>
      </div>
    </form>
  );
};

const KeyIcon = () => <Lock size={15} className="text-mockbird-cyan" />;
