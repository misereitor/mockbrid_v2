import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, 
  Send, 
  Loader2, 
  Check, 
  AlertCircle, 
  ChevronDown, 
  ChevronUp, 
  Brain, 
  Plus, 
  Trash2, 
  Copy, 
  History, 
  MessageSquare, 
  CheckCircle2, 
  Workflow, 
  ShieldCheck, 
  Wrench, 
  Zap, 
  ListTodo,
  Target,
  X,
  RotateCcw,
  Undo2,
  Redo2,
  GitCompare,
  FileCode
} from 'lucide-react';
import { SelectedElementInfo } from './CanvasEditor';

export interface PlanItem {
  id: number;
  title: string;
  description: string;
}

export interface QualityAuditInfo {
  score: number;
  passed: boolean;
  issues: string[];
  suggestions: string[];
}

export interface DiffLine {
  type: 'added' | 'removed' | 'unchanged';
  text: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  patch?: string;
  patchType?: 'element' | 'full' | 'none';
  targetSelector?: string;
  targetMbId?: string;
  targetTag?: string;
  timestamp: string;
  mode?: 'agent' | 'chat';
  plan?: PlanItem[];
  audit?: QualityAuditInfo;
  
  // Snapshots de estado para rastreabilidade e reversão
  htmlSnapshotBefore?: string;
  htmlSnapshotAfter?: string;
  elementSnapshotBefore?: string;
  isApplied?: boolean;
  appliedAt?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: string;
  messages: ChatMessage[];
}

interface AIChatPanelProps {
  currentHtml: string;
  onApplyHtml: (newHtml: string) => void;
  onApplyElementPatch?: (newHtml: string, target?: { mbId?: string; selector?: string }) => void;
  selectedElement?: SelectedElementInfo | null;
  onClearSelectedElement?: () => void;
  initialPrompt?: string;
  onClose?: () => void;
  projectId?: string;
  onCaptureScreenshot?: () => Promise<string>;
}

export function cleanAndExtractHtml(text: string): string {
  if (!text) return '';
  
  // 1. Bloco de código com crases ```html ... ```
  const fenceMatch = text.match(/```(?:html)?\s*(<[\s\S]+?>[\s\S]*?)```/i);
  if (fenceMatch) {
    const inside = fenceMatch[1].trim();
    if (inside.includes('<') && inside.includes('>')) {
      return inside;
    }
  }

  // 2. Documento completo HTML
  const docMatch = text.match(/(<!DOCTYPE\s+html[\s\S]+?<\/html>|<html[\s\S]+?<\/html>)/i);
  if (docMatch) return docMatch[1].trim();

  // 3. Tags HTML estruturais comuns
  const tagMatch = text.match(/(<(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])\b[\s\S]+?<\/(?:div|section|main|header|footer|aside|article|form|nav|button|ul|ol|table|dialog|p|span|a|h[1-6])>)/i);
  if (tagMatch) return tagMatch[1].trim();

  // 4. Tags autocontidas (img, input)
  const selfMatch = text.match(/(<(?:img|input|hr|br)\b[^>]*\/?>)/i);
  if (selfMatch) return selfMatch[1].trim();

  return '';
}

export function computeDiffLines(oldText: string, newText: string): DiffLine[] {
  if (!oldText) {
    return newText.split('\n').map(line => ({ type: 'added', text: line }));
  }
  const oldLines = oldText.split('\n');
  const newLines = newText.split('\n');
  
  const diff: DiffLine[] = [];
  const oldSet = new Set(oldLines.map(l => l.trim()));
  const newSet = new Set(newLines.map(l => l.trim()));

  let i = 0;
  let j = 0;
  while (i < oldLines.length || j < newLines.length) {
    if (i < oldLines.length && j < newLines.length && oldLines[i].trim() === newLines[j].trim()) {
      diff.push({ type: 'unchanged', text: oldLines[i] });
      i++;
      j++;
    } else if (i < oldLines.length && !newSet.has(oldLines[i].trim())) {
      diff.push({ type: 'removed', text: oldLines[i] });
      i++;
    } else if (j < newLines.length && !oldSet.has(newLines[j].trim())) {
      diff.push({ type: 'added', text: newLines[j] });
      j++;
    } else if (j < newLines.length) {
      diff.push({ type: 'added', text: newLines[j] });
      j++;
    } else if (i < oldLines.length) {
      diff.push({ type: 'removed', text: oldLines[i] });
      i++;
    }
  }
  return diff;
}

export function AIChatPanel({ 
  currentHtml, 
  onApplyHtml, 
  onApplyElementPatch,
  selectedElement,
  onClearSelectedElement,
  initialPrompt, 
  projectId = 'default'
}: AIChatPanelProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([
    {
      id: 'sess_default',
      title: 'Conversa Inicial',
      createdAt: '',
      messages: []
    }
  ]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('sess_default');
  const [prompt, setPrompt] = useState(initialPrompt || '');
  const [loading, setLoading] = useState(false);
  const [executionMode, setExecutionMode] = useState<'agent' | 'chat'>('agent');

  // Estados do Agente (LangGraph)
  const [agentStep, setAgentStep] = useState<{ node: string; title: string; detail: string } | null>(null);
  const [agentPlan, setAgentPlan] = useState<PlanItem[]>([]);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [agentAudit, setAgentAudit] = useState<QualityAuditInfo | null>(null);

  // Estados do Chat Rápido
  const [streamingThought, setStreamingThought] = useState('');
  const [streamingContent, setStreamingContent] = useState('');
  const [showThought, setShowThought] = useState(false);

  // Diff e Reversão
  const [openDiffMsgId, setOpenDiffMsgId] = useState<string | null>(null);
  const [diffTabs, setDiffTabs] = useState<Record<string, 'unified' | 'split'>>({});
  
  // Modal de Rollback / Voltar Mensagem (estilo Antigravity)
  const [rewindTarget, setRewindTarget] = useState<{
    msgId: string;
    index: number;
    isUser: boolean;
    content: string;
    snapshotHtml?: string;
  } | null>(null);
  const [revertCodeOnRewind, setRevertCodeOnRewind] = useState<boolean>(true);
  const [reloadPromptOnRewind, setReloadPromptOnRewind] = useState<boolean>(true);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showSessionsDrawer, setShowSessionsDrawer] = useState(false);

  // Modelos disponíveis
  const [availableModels, setAvailableModels] = useState<string[]>([
    'bonsai-27b',
    'gpt-4o',
    'claude-3-7-sonnet',
    'gemini-2.0-flash'
  ]);
  const [selectedModel, setSelectedModel] = useState<string>('bonsai-27b');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const thoughtEndRef = useRef<HTMLDivElement>(null);
  const storageKey = `mockbird_chat_sessions_${projectId}`;

  // Carrega sessões salvas do localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed: ChatSession[] = JSON.parse(saved);
        if (parsed.length > 0) {
          setSessions(parsed);
          setCurrentSessionId(parsed[0].id);
          return;
        }
      }
    } catch (e) {
      console.error('Falha ao carregar sessões de chat:', e);
    }

    const defaultSession: ChatSession = {
      id: `sess_${Date.now()}`,
      title: 'Conversa Inicial',
      createdAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
      messages: []
    };
    setSessions([defaultSession]);
    setCurrentSessionId(defaultSession.id);
  }, [projectId, storageKey]);

  // Persiste sessões no localStorage
  useEffect(() => {
    if (sessions.length > 0) {
      try {
        localStorage.setItem(storageKey, JSON.stringify(sessions));
      } catch (e) {
        console.error('Erro ao persistir sessões:', e);
      }
    }
  }, [sessions, storageKey]);

  // Sincroniza initialPrompt externo
  useEffect(() => {
    if (initialPrompt) {
      setPrompt(initialPrompt);
    }
  }, [initialPrompt]);

  // Busca modelos reais configurados no backend
  useEffect(() => {
    fetch('/api/ai/providers')
      .then(r => r.json())
      .then(data => {
        if (data && data.length > 0) {
          const active = data[0];
          if (active.custom_models && active.custom_models.length > 0) {
            setAvailableModels(active.custom_models);
          }
          if (active.default_model) {
            setSelectedModel(active.default_model);
          }
        }
      })
      .catch(console.error);
  }, []);

  // Scroll automático
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [sessions, loading, agentStep]);

  useEffect(() => {
    if (loading && showThought) {
      thoughtEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [streamingThought, loading, showThought]);

  const currentSession = sessions.find(s => s.id === currentSessionId) || sessions[0] || {
    id: 'sess_fallback',
    title: 'Nova Conversa',
    createdAt: '',
    messages: []
  };
  const currentMessages = currentSession.messages || [];

  const handleCreateSession = () => {
    const newSession: ChatSession = {
      id: `sess_${Date.now()}`,
      title: `Conversa ${sessions.length + 1}`,
      createdAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
      messages: []
    };
    setSessions(prev => [newSession, ...prev]);
    setCurrentSessionId(newSession.id);
    setShowSessionsDrawer(false);
    setStreamingContent('');
    setStreamingThought('');
    setAgentStep(null);
    setAgentPlan([]);
    setAgentAudit(null);
    setErrorMessage(null);
  };

  const handleDeleteSession = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sessions.length <= 1) {
      setSessions([{
        id: `sess_${Date.now()}`,
        title: 'Nova Conversa',
        createdAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
        messages: []
      }]);
      return;
    }
    const filtered = sessions.filter(s => s.id !== id);
    setSessions(filtered);
    if (currentSessionId === id) {
      setCurrentSessionId(filtered[0].id);
    }
  };

  // Envio de instrução (Agente Autônomo ou Chat Rápido)
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || loading) return;

    // Snapshot do estado do HTML no momento do envio
    const currentSnapshot = currentHtml;

    const userMessage: ChatMessage = {
      id: `msg_user_${Date.now()}`,
      role: 'user',
      content: cleanPrompt,
      mode: executionMode,
      targetTag: selectedElement?.tag,
      targetSelector: selectedElement?.selector || (selectedElement?.mbId ? `#${selectedElement.mbId}` : undefined),
      htmlSnapshotBefore: currentSnapshot,
      timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    };

    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        const title = s.messages.length === 0
          ? (cleanPrompt.length > 28 ? cleanPrompt.substring(0, 28) + '...' : cleanPrompt)
          : s.title;
        return {
          ...s,
          title,
          messages: [...s.messages, userMessage]
        };
      }
      return s;
    }));

    setPrompt('');
    setLoading(true);
    setStreamingContent('');
    setStreamingThought('');
    setAgentStep(null);
    setAgentPlan([]);
    setActiveTool(null);
    setAgentAudit(null);
    setErrorMessage(null);

    // FLUXO 1: AGENTE AUTÔNOMO (LangGraph)
    if (executionMode === 'agent') {
      try {
        const response = await fetch('/api/ai/agent/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: cleanPrompt,
            current_html: currentHtml,
            target_element: selectedElement ? {
              mbId: selectedElement.mbId,
              tag: selectedElement.tag,
              selector: selectedElement.selector,
              snippet: selectedElement.snippet,
              styles: selectedElement.styles
            } : undefined,
            model_name: selectedModel
          })
        });

        if (!response.ok || !response.body) {
          throw new Error(`Servidor de Agente retornou HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let finalPatch = '';
        let finalPatchType: 'element' | 'full' | 'none' = 'none';
        let finalTargetSelector = '';
        let finalTargetMbId = '';
        let finalTargetTag = '';
        let finalSummary = '';
        let finalReasoning = '';
        let collectedPlan: PlanItem[] = [];
        let collectedAudit: QualityAuditInfo | null = null;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            const jsonStr = trimmed.replace('data:', '').trim();
            if (!jsonStr) continue;

            try {
              const ev = JSON.parse(jsonStr);

              if (ev.type === 'node_start') {
                setAgentStep({ node: ev.node, title: ev.title, detail: ev.detail });
              } else if (ev.type === 'node_progress') {
                if (ev.detail && agentStep) {
                  setAgentStep({ ...agentStep, detail: ev.detail });
                }
              } else if (ev.type === 'plan_ready') {
                collectedPlan = ev.plan || [];
                setAgentPlan(collectedPlan);
              } else if (ev.type === 'tool_call') {
                setActiveTool(ev.tool);
              } else if (ev.type === 'audit_result') {
                collectedAudit = {
                  score: ev.score,
                  passed: ev.passed,
                  issues: ev.issues || [],
                  suggestions: ev.suggestions || []
                };
                setAgentAudit(collectedAudit);
              } else if (ev.type === 'agent_done') {
                finalPatch = ev.patch || '';
                finalPatchType = ev.patch_type || (finalPatch ? (selectedElement ? 'element' : 'full') : 'none');
                finalTargetSelector = ev.target_selector || selectedElement?.selector || '';
                finalTargetMbId = ev.target_mb_id || selectedElement?.mbId || '';
                finalTargetTag = ev.target_tag || selectedElement?.tag || '';
                finalSummary = ev.summary || '';
                finalReasoning = ev.reasoning || '';
                if (ev.audit) collectedAudit = ev.audit;
                if (ev.plan) collectedPlan = ev.plan;
              } else if (ev.type === 'error') {
                setErrorMessage(ev.detail || 'Ocorreu um erro no grafo do agente.');
              }
            } catch {
              // chunk parcial SSE
            }
          }
        }

        const effectivePatch = cleanAndExtractHtml(finalPatch);
        const assistantMessage: ChatMessage = {
          id: `msg_asst_${Date.now()}`,
          role: 'assistant',
          content: finalSummary || 'Instrução processada com sucesso pelo Agente.',
          reasoning: finalReasoning.trim() || undefined,
          patch: effectivePatch || undefined,
          patchType: effectivePatch ? finalPatchType : 'none',
          targetSelector: finalTargetSelector,
          targetMbId: finalTargetMbId,
          targetTag: finalTargetTag,
          mode: 'agent',
          plan: collectedPlan.length > 0 ? collectedPlan : undefined,
          audit: collectedAudit || undefined,
          htmlSnapshotBefore: currentSnapshot,
          elementSnapshotBefore: selectedElement?.snippet,
          isApplied: false,
          timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
        };

        setSessions(prev => prev.map(s => {
          if (s.id === currentSessionId) {
            return {
              ...s,
              messages: [...s.messages, assistantMessage]
            };
          }
          return s;
        }));

      } catch (err: any) {
        setErrorMessage(err.message || 'Falha na execução do Agente.');
      } finally {
        setLoading(false);
        setAgentStep(null);
        setActiveTool(null);
      }
      return;
    }

    // FLUXO 2: CHAT RÁPIDO (Direct Stream)
    let accumulatedReasoning = '';
    let accumulatedContent = '';
    let finalPatchFromServer = '';

    try {
      const response = await fetch('/api/ai/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: cleanPrompt,
          current_html: currentHtml,
          target_element: selectedElement ? {
            mbId: selectedElement.mbId,
            tag: selectedElement.tag,
            selector: selectedElement.selector,
            snippet: selectedElement.snippet
          } : undefined,
          model_name: selectedModel
        })
      });

      if (!response.ok || !response.body) {
        throw new Error(`Servidor de IA retornou status HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const jsonStr = trimmed.replace('data:', '').trim();
          if (!jsonStr) continue;

          try {
            const ev = JSON.parse(jsonStr);
            if (ev.type === 'thinking') {
              accumulatedReasoning += ev.text;
              setStreamingThought(prev => prev + ev.text);
            } else if (ev.type === 'content') {
              accumulatedContent += ev.text;
              setStreamingContent(prev => prev + ev.text);
            } else if (ev.type === 'done') {
              finalPatchFromServer = ev.patch || '';
            } else if (ev.type === 'error') {
              setErrorMessage(ev.detail || 'Ocorreu um erro durante a inferência.');
            }
          } catch {
            // chunk parcial
          }
        }
      }

      const effectivePatch = cleanAndExtractHtml(finalPatchFromServer || accumulatedContent);
      const assistantMessage: ChatMessage = {
        id: `msg_asst_${Date.now()}`,
        role: 'assistant',
        content: accumulatedContent.trim() ? accumulatedContent.replace(/```(?:html)?[\s\S]*?```/gi, '').trim() : 'Resposta processada.',
        reasoning: accumulatedReasoning.trim() || undefined,
        patch: effectivePatch || undefined,
        patchType: effectivePatch ? (selectedElement ? 'element' : 'full') : 'none',
        targetTag: selectedElement?.tag,
        targetSelector: selectedElement?.selector,
        targetMbId: selectedElement?.mbId,
        mode: 'chat',
        htmlSnapshotBefore: currentSnapshot,
        elementSnapshotBefore: selectedElement?.snippet,
        isApplied: false,
        timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
      };

      setSessions(prev => prev.map(s => {
        if (s.id === currentSessionId) {
          return {
            ...s,
            messages: [...s.messages, assistantMessage]
          };
        }
        return s;
      }));

    } catch (err: any) {
      setErrorMessage(err.message || 'Falha ao conectar com o servidor de IA.');
    } finally {
      setLoading(false);
      setStreamingThought('');
      setStreamingContent('');
    }
  };

  // Aplicar versão na tela inteira com snapshot de reversão
  const handleApplyVersion = (msgId: string, patchHtml: string) => {
    if (!patchHtml) return;
    const clean = cleanAndExtractHtml(patchHtml);
    const snapshotBefore = currentHtml;

    onApplyHtml(clean);
    setAppliedId(msgId);
    setTimeout(() => setAppliedId(null), 3000);

    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return {
          ...s,
          messages: s.messages.map(m => {
            if (m.id === msgId) {
              return {
                ...m,
                isApplied: true,
                htmlSnapshotBefore: m.htmlSnapshotBefore || snapshotBefore,
                htmlSnapshotAfter: clean,
                appliedAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
              };
            }
            return m;
          })
        };
      }
      return s;
    }));
  };

  // Aplicar alteração cirúrgica no elemento com snapshot de reversão
  const handleApplyElement = (msgId: string, patchHtml: string, target?: { selector?: string; mbId?: string }) => {
    if (!patchHtml) return;
    const clean = cleanAndExtractHtml(patchHtml);
    const snapshotBefore = currentHtml;

    if (onApplyElementPatch) {
      onApplyElementPatch(clean, target);
    } else {
      onApplyHtml(clean);
    }
    setAppliedId(msgId);
    setTimeout(() => setAppliedId(null), 3000);

    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return {
          ...s,
          messages: s.messages.map(m => {
            if (m.id === msgId) {
              return {
                ...m,
                isApplied: true,
                htmlSnapshotBefore: m.htmlSnapshotBefore || snapshotBefore,
                htmlSnapshotAfter: clean,
                appliedAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
              };
            }
            return m;
          })
        };
      }
      return s;
    }));
  };

  // Reverter alteração (Desfazer código aplicado)
  const handleRevertVersion = (msgId: string) => {
    const msg = currentMessages.find(m => m.id === msgId);
    if (!msg || !msg.htmlSnapshotBefore) return;

    onApplyHtml(msg.htmlSnapshotBefore);

    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return {
          ...s,
          messages: s.messages.map(m => {
            if (m.id === msgId) {
              return {
                ...m,
                isApplied: false
              };
            }
            return m;
          })
        };
      }
      return s;
    }));
  };

  // Reaplicar alteração revertida
  const handleReapplyVersion = (msgId: string) => {
    const msg = currentMessages.find(m => m.id === msgId);
    if (!msg || !msg.patch) return;

    if (msg.patchType === 'element' && onApplyElementPatch) {
      onApplyElementPatch(msg.patch, { selector: msg.targetSelector, mbId: msg.targetMbId });
    } else {
      onApplyHtml(msg.patch);
    }

    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return {
          ...s,
          messages: s.messages.map(m => {
            if (m.id === msgId) {
              return {
                ...m,
                isApplied: true,
                appliedAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
              };
            }
            return m;
          })
        };
      }
      return s;
    }));
  };

  // Confirmar Rollback / Voltar Mensagens no Chat
  const handleConfirmRewind = () => {
    if (!rewindTarget) return;

    const targetIndex = rewindTarget.index;
    const shouldRevertCode = revertCodeOnRewind;
    const shouldReloadPrompt = reloadPromptOnRewind && rewindTarget.isUser;

    // Se optou por reverter o código da tela também
    if (shouldRevertCode && rewindTarget.snapshotHtml) {
      onApplyHtml(rewindTarget.snapshotHtml);
    }

    // Se for recarregar o prompt no textarea
    if (shouldReloadPrompt) {
      setPrompt(rewindTarget.content);
    }

    // Trunca as mensagens da sessão mantendo até este ponto
    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        const newMessages = shouldReloadPrompt
          ? s.messages.slice(0, targetIndex) // remove a mensagem atual do histórico para o usuário reeditar
          : s.messages.slice(0, targetIndex + 1); // preserva a mensagem alvo
        return {
          ...s,
          messages: newMessages
        };
      }
      return s;
    }));

    setRewindTarget(null);
  };

  const handleCopyCode = (msgId: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(msgId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="w-full flex flex-col h-full bg-mockbird-surface text-slate-100 select-none overflow-hidden relative">
      {/* Header com Seletor de Modelo e Histórico */}
      <div className="p-3 border-b border-mockbird-border flex items-center justify-between gap-2 shrink-0 bg-mockbird-card/40">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1.5 rounded-lg bg-mockbird-blue/20 text-mockbird-cyan shrink-0">
            {executionMode === 'agent' ? <Workflow size={16} /> : <Sparkles size={16} />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-bold text-white truncate">
                {executionMode === 'agent' ? 'Agente Autônomo' : 'Assistente IA'}
              </span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-medium ${
                executionMode === 'agent' ? 'bg-indigo-500/10 text-indigo-400' : 'bg-emerald-500/10 text-emerald-400'
              }`}>
                {executionMode === 'agent' ? 'LangGraph' : 'Chat'}
              </span>
            </div>
            <p className="text-[10px] text-slate-400 truncate">Edição cirúrgica, reversão e diff visual</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowSessionsDrawer(!showSessionsDrawer)}
            className={`p-1.5 rounded-lg border transition-all text-xs flex items-center gap-1 ${
              showSessionsDrawer
                ? 'bg-mockbird-blue/20 border-mockbird-blue text-white'
                : 'bg-mockbird-surface border-mockbird-border text-slate-300 hover:text-white'
            }`}
            title="Histórico de Conversas"
          >
            <History size={14} />
            <span className="text-[11px] hidden sm:inline">{sessions.length}</span>
          </button>

          <button
            type="button"
            onClick={handleCreateSession}
            className="p-1.5 rounded-lg bg-mockbird-surface border border-mockbird-border hover:bg-mockbird-card text-slate-300 hover:text-white transition"
            title="Nova Conversa"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* Seletor de Modo: Agente (LangGraph) vs Chat Rápido */}
      <div className="px-3 py-1.5 bg-[#0a0a0c] border-b border-mockbird-border flex items-center justify-between text-xs">
        <div className="flex items-center gap-1 p-0.5 rounded-lg bg-mockbird-surface border border-mockbird-border text-[11px]">
          <button
            type="button"
            onClick={() => setExecutionMode('agent')}
            className={`px-2 py-0.5 rounded-md font-semibold flex items-center gap-1.5 transition-all ${
              executionMode === 'agent'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Workflow size={12} />
            <span>Agente LangGraph</span>
          </button>
          <button
            type="button"
            onClick={() => setExecutionMode('chat')}
            className={`px-2 py-0.5 rounded-md font-semibold flex items-center gap-1.5 transition-all ${
              executionMode === 'chat'
                ? 'bg-mockbird-blue text-white shadow-sm'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Zap size={12} />
            <span>Chat Rápido</span>
          </button>
        </div>

        {/* Modelo Selecionado */}
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="bg-mockbird-bg border border-mockbird-border rounded-md px-2 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-mockbird-blue cursor-pointer"
        >
          {availableModels.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      {/* Gaveta de Histórico de Sessões */}
      {showSessionsDrawer && (
        <div className="p-2.5 bg-mockbird-bg border-b border-mockbird-border space-y-1.5 max-h-48 overflow-y-auto shrink-0 animate-in slide-in-from-top duration-150">
          <div className="flex items-center justify-between px-1 text-[11px] text-slate-400 font-semibold">
            <span>Conversas Salvas</span>
            <button
              onClick={handleCreateSession}
              className="text-mockbird-cyan hover:underline flex items-center gap-1 text-[10px]"
            >
              <Plus size={11} /> Nova
            </button>
          </div>
          {sessions.map(s => {
            const isCurr = s.id === currentSessionId;
            return (
              <div
                key={s.id}
                onClick={() => {
                  setCurrentSessionId(s.id);
                  setShowSessionsDrawer(false);
                }}
                className={`group flex items-center justify-between p-2 rounded-lg cursor-pointer transition text-xs border ${
                  isCurr
                    ? 'bg-mockbird-card border-mockbird-blue/50 text-white'
                    : 'hover:bg-mockbird-card/60 text-slate-300'
                }`}
              >
                <div className="min-w-0 flex items-center gap-2 truncate">
                  <MessageSquare size={13} className={isCurr ? 'text-mockbird-cyan' : 'text-slate-500'} />
                  <span className="truncate text-[11px] font-medium">{s.title}</span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <span className="text-[10px] text-slate-500">{s.messages.length} msg</span>
                  <button
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 hover:text-rose-400 text-slate-500 transition"
                    title="Excluir conversa"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Lista de Mensagens do Chat */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3.5 text-xs">
        {currentMessages.length === 0 && !loading && (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-400 space-y-3">
            <div className="p-3 rounded-2xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <Workflow size={28} />
            </div>
            <div className="space-y-1">
              <h4 className="text-xs font-bold text-white">Agente Inteligente do Mockbird v2</h4>
              <p className="text-[11px] text-slate-400 max-w-[260px] leading-relaxed">
                Você pode pedir alterações, comparar diffs visuais, reverter qualquer mudança e voltar mensagens com um clique.
              </p>
            </div>

            {/* Sugestões rápidas de prompt */}
            <div className="pt-2 w-full max-w-[260px] space-y-1.5 text-left">
              <button
                type="button"
                onClick={() => setPrompt('Cria uma landing page para concessionária Honda com hero do Civic Type R, grid bento de modelos e simulador de financiamento')}
                className="w-full p-2 rounded-lg bg-mockbird-card hover:bg-mockbird-card/80 border border-mockbird-border text-[11px] text-slate-300 transition text-left"
              >
                🏎️ Concessionária Honda com Bento Grid
              </button>
              <button
                type="button"
                onClick={() => setPrompt('O layout tá com alinhamento quebrado no cabeçalho e nos cards. Poderia consertar a estrutura mantendo os elementos?')}
                className="w-full p-2 rounded-lg bg-mockbird-card hover:bg-mockbird-card/80 border border-mockbird-border text-[11px] text-slate-300 transition text-left"
              >
                🛠️ Consertar alinhamento e layout quebrado
              </button>
            </div>
          </div>
        )}

        {currentMessages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          const isDiffOpen = openDiffMsgId === msg.id;
          const currentDiffTab = diffTabs[msg.id] || 'unified';

          // Calcula diff se houver patch
          const diffLines = msg.patch 
            ? computeDiffLines(
                msg.patchType === 'element' 
                  ? (msg.elementSnapshotBefore || '') 
                  : (msg.htmlSnapshotBefore || ''), 
                msg.patch
              )
            : [];
          
          const addedCount = diffLines.filter(d => d.type === 'added').length;
          const removedCount = diffLines.filter(d => d.type === 'removed').length;

          if (isUser) {
            return (
              <div key={msg.id} className="group relative flex justify-end">
                <div className="bg-mockbird-blue text-white rounded-2xl rounded-tr-sm px-3.5 py-2.5 max-w-[88%] text-xs shadow-md leading-relaxed select-text space-y-1 relative">
                  <div className="flex items-center justify-between gap-2 text-[10px] text-blue-200">
                    <div className="flex items-center gap-1.5">
                      {msg.mode === 'agent' ? <Workflow size={11} /> : <Zap size={11} />}
                      <span>{msg.mode === 'agent' ? 'Agente LangGraph' : 'Chat Direto'}</span>
                      {msg.targetTag && (
                        <span className="ml-1 px-1.5 py-0.2 bg-black/20 rounded font-mono text-emerald-300">
                          alvo: &lt;{msg.targetTag}&gt;
                        </span>
                      )}
                    </div>

                    {/* Botão de Rollback / Voltar Mensagem (estilo Antigravity) */}
                    <button
                      type="button"
                      onClick={() => setRewindTarget({
                        msgId: msg.id,
                        index: idx,
                        isUser: true,
                        content: msg.content,
                        snapshotHtml: msg.htmlSnapshotBefore || currentHtml
                      })}
                      className="opacity-0 group-hover:opacity-100 hover:text-white p-0.5 rounded text-blue-200 hover:bg-black/20 transition flex items-center gap-1 text-[9px]"
                      title="Voltar conversa até aqui (Rollback)"
                    >
                      <RotateCcw size={10} />
                      <span>Voltar</span>
                    </button>
                  </div>
                  <div>{msg.content}</div>
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className="group relative flex flex-col space-y-2.5 max-w-[96%] animate-in fade-in duration-200">
              {/* Botão de Rollback da mensagem do assistente */}
              <div className="flex items-center justify-between text-[10px] text-slate-500 px-1">
                <span className="font-mono">{msg.timestamp}</span>
                <button
                  type="button"
                  onClick={() => setRewindTarget({
                    msgId: msg.id,
                    index: idx,
                    isUser: false,
                    content: msg.content,
                    snapshotHtml: msg.htmlSnapshotBefore || currentHtml
                  })}
                  className="opacity-0 group-hover:opacity-100 hover:text-mockbird-cyan p-0.5 rounded text-slate-400 hover:bg-mockbird-card transition flex items-center gap-1 text-[10px]"
                  title="Voltar conversa até esta resposta"
                >
                  <RotateCcw size={11} />
                  <span>Voltar até aqui</span>
                </button>
              </div>

              {/* Plano Arquitetural Executado */}
              {msg.plan && msg.plan.length > 0 && (
                <div className="rounded-xl border border-mockbird-border bg-[#0a0a0c] p-2.5 space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-mockbird-cyan">
                    <ListTodo size={13} />
                    <span>Plano Arquitetural Executado ({msg.plan.length} blocos)</span>
                  </div>
                  <div className="space-y-1">
                    {msg.plan.map((p) => (
                      <div key={p.id} className="flex items-start gap-2 text-[10px] text-slate-300 bg-mockbird-surface/80 p-1.5 rounded-lg border border-mockbird-border/40">
                        <span className="font-mono font-bold text-emerald-400 shrink-0">✓ {p.id}.</span>
                        <div>
                          <strong className="text-white">{p.title}:</strong> <span className="text-slate-400">{p.description}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Selo de Auditoria de Qualidade */}
              {msg.audit && (
                <div className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-[11px] text-emerald-300">
                  <div className="flex items-center gap-1.5">
                    <ShieldCheck size={14} className="text-emerald-400" />
                    <span>Auditoria de Qualidade Antirresumo</span>
                  </div>
                  <span className="font-mono font-bold">{msg.audit.score}/100</span>
                </div>
              )}

              {/* Raciocínio Expansível */}
              {msg.reasoning && (
                <div className="rounded-xl border border-mockbird-border bg-[#0a0a0c] overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setShowThought(!showThought)}
                    className="w-full px-3 py-1.5 flex items-center justify-between text-[11px] text-slate-400 hover:text-white transition-colors"
                  >
                    <div className="flex items-center gap-1.5 text-mockbird-cyan">
                      <Brain size={13} />
                      <span className="font-medium">Raciocínio da IA</span>
                    </div>
                    {showThought ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                  </button>
                  {showThought && (
                    <div className="p-3 text-[10px] font-mono text-slate-400 max-h-36 overflow-y-auto whitespace-pre-wrap leading-relaxed select-text border-t border-mockbird-border/40">
                      {msg.reasoning}
                    </div>
                  )}
                </div>
              )}

              {/* Mensagem / Explicação do Assistente em Português */}
              {msg.content && (
                <div className="bg-mockbird-card border border-mockbird-border rounded-2xl rounded-tl-sm p-3 text-xs text-slate-200 shadow-sm leading-relaxed select-text whitespace-pre-wrap">
                  {msg.content}
                </div>
              )}

              {/* Card de Código Gerado com Visualizador de Alterações (Diff) e Reversão */}
              {msg.patch && msg.patch.trim().length > 0 && (
                <div className="p-3.5 rounded-xl bg-mockbird-card border border-mockbird-border shadow-panel space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Sparkles size={14} className="text-mockbird-cyan" />
                      {msg.patchType === 'element' 
                        ? `Alteração Cirúrgica <${msg.targetTag || 'alvo'}>`
                        : `Versão da Tela (${msg.timestamp})`}
                    </span>
                    <div className="flex items-center gap-2">
                      {/* Botão de Diff / Mostrar Alterações */}
                      <button
                        type="button"
                        onClick={() => setOpenDiffMsgId(isDiffOpen ? null : msg.id)}
                        className={`text-[11px] px-2 py-0.5 rounded-md border flex items-center gap-1 font-semibold transition ${
                          isDiffOpen
                            ? 'bg-mockbird-blue/20 border-mockbird-blue text-white'
                            : 'bg-[#0a0a0c] border-mockbird-border text-slate-300 hover:text-white'
                        }`}
                        title="Ver alterações em formato diff"
                      >
                        <GitCompare size={12} className={isDiffOpen ? 'text-mockbird-cyan' : 'text-slate-400'} />
                        <span>{isDiffOpen ? 'Fechar Diff' : 'Ver Alterações'}</span>
                        {addedCount > 0 && <span className="text-emerald-400 font-mono text-[10px]">+{addedCount}</span>}
                        {removedCount > 0 && <span className="text-rose-400 font-mono text-[10px]">-{removedCount}</span>}
                      </button>

                      <button
                        type="button"
                        onClick={() => handleCopyCode(msg.id, msg.patch || '')}
                        className="text-[11px] text-mockbird-cyan hover:underline flex items-center gap-1 font-semibold"
                        title="Copiar HTML"
                      >
                        {copiedId === msg.id ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                        <span>{copiedId === msg.id ? 'Copiado!' : 'Copiar'}</span>
                      </button>
                    </div>
                  </div>

                  {msg.patchType === 'element' && (msg.targetSelector || msg.targetMbId) && (
                    <div className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                      <span>Alvo:</span>
                      <span className="text-emerald-300 font-semibold">{msg.targetSelector || `#${msg.targetMbId}`}</span>
                    </div>
                  )}

                  {/* Visualizador de Diff (Expansível) */}
                  {isDiffOpen ? (
                    <div className="rounded-xl border border-mockbird-border bg-[#08080a] overflow-hidden space-y-1.5 animate-in fade-in duration-150">
                      <div className="px-3 py-1.5 bg-[#0e0e12] border-b border-mockbird-border/60 flex items-center justify-between text-[10px]">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-300 flex items-center gap-1">
                            <FileCode size={12} className="text-mockbird-cyan" />
                            Comparação de Código
                          </span>
                          <span className="text-emerald-400 font-mono">+{addedCount} adicionadas</span>
                          <span className="text-rose-400 font-mono">-{removedCount} removidas</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setDiffTabs(prev => ({ ...prev, [msg.id]: 'unified' }))}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium transition ${
                              currentDiffTab === 'unified' ? 'bg-mockbird-blue text-white' : 'text-slate-400 hover:text-white'
                            }`}
                          >
                            Diff Colorido
                          </button>
                          <button
                            type="button"
                            onClick={() => setDiffTabs(prev => ({ ...prev, [msg.id]: 'split' }))}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium transition ${
                              currentDiffTab === 'split' ? 'bg-mockbird-blue text-white' : 'text-slate-400 hover:text-white'
                            }`}
                          >
                            Antes vs Depois
                          </button>
                        </div>
                      </div>

                      {currentDiffTab === 'unified' ? (
                        <div className="p-2 font-mono text-[10px] max-h-48 overflow-y-auto space-y-0.5 select-text">
                          {diffLines.map((d, i) => (
                            <div 
                              key={i} 
                              className={`px-1.5 py-0.5 rounded flex items-start gap-2 leading-tight ${
                                d.type === 'added'
                                  ? 'bg-emerald-950/40 text-emerald-300 border-l-2 border-emerald-500'
                                  : d.type === 'removed'
                                  ? 'bg-rose-950/40 text-rose-300 border-l-2 border-rose-500'
                                  : 'text-slate-400'
                              }`}
                            >
                              <span className="font-bold select-none w-3 text-center shrink-0">
                                {d.type === 'added' ? '+' : d.type === 'removed' ? '-' : ' '}
                              </span>
                              <span className="whitespace-pre-wrap break-all">{d.text}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 gap-1 p-2 font-mono text-[9px] max-h-48 overflow-y-auto">
                          <div className="p-2 rounded bg-rose-950/20 border border-rose-500/20 text-rose-200 space-y-1">
                            <span className="text-[10px] font-bold text-rose-400 block pb-1 border-b border-rose-500/20">Original (Antes)</span>
                            <pre className="whitespace-pre-wrap break-all select-text">
                              {msg.patchType === 'element' ? (msg.elementSnapshotBefore || '(sem snapshot)') : (msg.htmlSnapshotBefore?.slice(0, 400) || '(sem snapshot)')}
                            </pre>
                          </div>
                          <div className="p-2 rounded bg-emerald-950/20 border border-emerald-500/20 text-emerald-200 space-y-1">
                            <span className="text-[10px] font-bold text-emerald-400 block pb-1 border-b border-emerald-500/20">Novo (Depois)</span>
                            <pre className="whitespace-pre-wrap break-all select-text">
                              {msg.patch.slice(0, 400)}...
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    /* Preview Compacto */
                    <div className="p-2 rounded-lg bg-[#0a0a0c] border border-mockbird-border/60 text-[10px] font-mono text-slate-400 max-h-24 overflow-y-auto whitespace-pre-wrap select-text">
                      {msg.patch.slice(0, 260)}...
                    </div>
                  )}

                  {/* Botões de Ação com Suporte a Reversão (Undo) e Reaplicação (Redo) */}
                  {msg.isApplied ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 py-2 px-3 rounded-xl text-xs font-semibold bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 flex items-center justify-center gap-1.5">
                        <CheckCircle2 size={14} className="text-emerald-400" />
                        <span>Aplicado {msg.appliedAt ? `(${msg.appliedAt})` : ''}</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRevertVersion(msg.id)}
                        className="px-3.5 py-2 rounded-xl text-xs font-bold bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/40 text-amber-300 flex items-center justify-center gap-1.5 transition-all shadow-sm"
                        title="Reverter alteração (desfazer do Canvas)"
                      >
                        <Undo2 size={13} />
                        <span>Reverter</span>
                      </button>
                    </div>
                  ) : msg.htmlSnapshotBefore && msg.appliedAt ? (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 py-2 px-3 rounded-xl text-xs font-semibold bg-slate-800/60 border border-mockbird-border text-slate-400 flex items-center justify-center gap-1.5">
                        <RotateCcw size={13} className="text-slate-500" />
                        <span>Alteração Revertida</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleReapplyVersion(msg.id)}
                        className="px-3.5 py-2 rounded-xl text-xs font-bold bg-mockbird-blue hover:bg-mockbird-bluedark text-white flex items-center justify-center gap-1.5 transition-all shadow-md"
                        title="Reaplicar esta alteração no Canvas"
                      >
                        <Redo2 size={13} />
                        <span>Reaplicar</span>
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        if (msg.patchType === 'element') {
                          handleApplyElement(msg.id, msg.patch || '', { selector: msg.targetSelector, mbId: msg.targetMbId });
                        } else {
                          handleApplyVersion(msg.id, msg.patch || '');
                        }
                      }}
                      className={`w-full py-2.5 rounded-xl text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-md ${
                        appliedId === msg.id
                          ? 'bg-emerald-600 text-white'
                          : 'bg-mockbird-blue hover:bg-mockbird-bluedark text-white'
                      }`}
                    >
                      {appliedId === msg.id ? (
                        <>
                          <CheckCircle2 size={15} />
                          <span>✓ Aplicado com Sucesso!</span>
                        </>
                      ) : (
                        <>
                          <Sparkles size={15} />
                          <span>
                            {msg.patchType === 'element' ? 'Aplicar no Elemento Selecionado' : 'Aplicar na Tela'}
                          </span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Execução Ativa do Agente LangGraph */}
        {loading && executionMode === 'agent' && (
          <div className="space-y-2.5 max-w-[96%] animate-in fade-in">
            {/* Card do Nó Ativo */}
            <div className="p-3 rounded-xl bg-indigo-950/30 border border-indigo-500/30 text-xs space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-indigo-300 font-bold">
                  <Loader2 size={14} className="animate-spin text-mockbird-cyan" />
                  <span>{agentStep?.title || 'Inicializando Grafo do Agente...'}</span>
                </div>
                {activeTool && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono flex items-center gap-1">
                    <Wrench size={10} /> {activeTool}
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                {agentStep?.detail || 'Inspecionando contexto e selecionando ferramentas ideais...'}
              </p>
              {agentAudit && (
                <div className="flex items-center gap-1.5 pt-1 text-[10px] text-emerald-400 font-semibold border-t border-indigo-500/20">
                  <ShieldCheck size={12} />
                  <span>Auditoria Antirresumo: {agentAudit.score}/100</span>
                </div>
              )}
            </div>

            {/* Plano de Ação em Andamento */}
            {agentPlan.length > 0 && (
              <div className="p-2.5 rounded-xl border border-mockbird-border bg-[#0a0a0c] space-y-1.5">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-mockbird-cyan">
                  <Workflow size={13} />
                  <span>Plano Arquitetural ({agentPlan.length} etapas)</span>
                </div>
                <div className="space-y-1">
                  {agentPlan.map((p) => (
                    <div key={p.id} className="flex items-start gap-2 text-[10px] text-slate-300 bg-mockbird-surface p-1.5 rounded-lg border border-mockbird-border/40">
                      <span className="font-mono font-bold text-mockbird-cyan shrink-0">{p.id}.</span>
                      <div>
                        <strong className="text-white">{p.title}:</strong> <span className="text-slate-400">{p.description}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Streaming Ativo do Chat Direto */}
        {loading && executionMode === 'chat' && (
          <div className="space-y-2 max-w-[96%] animate-in fade-in">
            {streamingThought && (
              <div className="rounded-xl border border-mockbird-border bg-[#0a0a0c] p-2.5">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-mockbird-cyan mb-1.5">
                  <Brain size={13} className="animate-pulse" />
                  <span>Pensando na estrutura da tela...</span>
                </div>
                <div className="text-[10px] font-mono text-slate-400 max-h-28 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                  {streamingThought}
                  <div ref={thoughtEndRef} />
                </div>
              </div>
            )}

            {streamingContent && (
              <div className="bg-mockbird-card border border-mockbird-border rounded-2xl rounded-tl-sm p-3 text-xs text-slate-200">
                <div className="flex items-center gap-2 text-mockbird-cyan mb-1 text-[11px] font-semibold">
                  <Loader2 size={12} className="animate-spin" />
                  <span>Processando resposta...</span>
                </div>
                <div className="text-[10px] font-mono text-slate-400 max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {streamingContent}
                </div>
              </div>
            )}

            {!streamingThought && !streamingContent && (
              <div className="flex items-center gap-2 text-xs text-slate-400 p-2.5 rounded-xl bg-mockbird-card border border-mockbird-border">
                <Loader2 size={14} className="animate-spin text-mockbird-cyan" />
                <span>Conectando com o modelo {selectedModel}...</span>
              </div>
            )}
          </div>
        )}

        {/* Mensagem de Erro */}
        {errorMessage && (
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-2 animate-in fade-in">
            <AlertCircle size={15} className="shrink-0 mt-0.5 text-rose-400" />
            <div className="space-y-1">
              <span className="font-semibold block">Erro na inferência:</span>
              <p className="text-[11px] leading-relaxed">{errorMessage}</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input de Prompt no Rodapé com Badge de Alvo Cirúrgico */}
      <form onSubmit={handleSendMessage} className="p-3 border-t border-mockbird-border bg-mockbird-card/40 space-y-2 shrink-0">
        {/* Badge de Alvo Selecionado */}
        {selectedElement && (
          <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-[11px] text-indigo-300 animate-in fade-in">
            <div className="flex items-center gap-1.5 truncate">
              <Target size={13} className="text-mockbird-cyan shrink-0" />
              <span className="font-semibold text-white">&lt;{selectedElement.tag}&gt;</span>
              <span className="font-mono text-slate-300 truncate">
                {selectedElement.selector || (selectedElement.mbId ? `#${selectedElement.mbId}` : '')}
              </span>
              {selectedElement.snippet && (
                <span className="text-slate-400 truncate italic">“{selectedElement.snippet}”</span>
              )}
            </div>
            {onClearSelectedElement && (
              <button
                type="button"
                onClick={onClearSelectedElement}
                className="p-0.5 rounded hover:bg-indigo-500/20 text-slate-400 hover:text-white transition shrink-0 ml-1"
                title="Desmarcar elemento (voltar para a tela inteira)"
              >
                <X size={12} />
              </button>
            )}
          </div>
        )}

        <div className="relative">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder={
              selectedElement
                ? `Descreva o que alterar no elemento <${selectedElement.tag}> (ex: trocar texto, mudar cor)...`
                : executionMode === 'agent'
                ? 'Instrua o Agente (ele analisa a intenção, inspeciona e valida o código)...'
                : 'Ex: Cria uma landing page para concessionária Honda com hero e grid...'
            }
            rows={3}
            disabled={loading}
            className="w-full bg-mockbird-bg border border-mockbird-border focus:border-mockbird-blue rounded-xl p-2.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none resize-none transition leading-relaxed disabled:opacity-60"
          />
        </div>

        <button
          type="submit"
          disabled={loading || !prompt.trim()}
          className="w-full py-2.5 bg-mockbird-blue hover:bg-mockbird-bluedark disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all shadow-md"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin text-mockbird-cyan" />
              <span>{executionMode === 'agent' ? 'Agente em Execução...' : 'Gerando Código...'}</span>
            </>
          ) : (
            <>
              {selectedElement ? (
                <>
                  <Target size={14} className="text-mockbird-cyan" />
                  <span>Modificar Elemento Selecionado</span>
                </>
              ) : executionMode === 'agent' ? (
                <>
                  <Workflow size={14} />
                  <span>Executar Agente Autônomo</span>
                </>
              ) : (
                <>
                  <Send size={14} />
                  <span>Enviar Instrução</span>
                </>
              )}
            </>
          )}
        </button>
      </form>

      {/* Modal de Confirmação de Rollback / Voltar Mensagem (Estilo Antigravity) */}
      {rewindTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="bg-mockbird-surface border border-mockbird-border rounded-2xl p-4 max-w-sm w-full space-y-4 shadow-2xl animate-in zoom-in-95 duration-150 text-slate-200">
            <div className="flex items-center gap-2 text-mockbird-cyan font-bold text-xs">
              <RotateCcw size={16} />
              <span>Voltar histórico até esta mensagem?</span>
            </div>

            <p className="text-[11px] text-slate-400 leading-relaxed">
              Você está retrocedendo a conversa. As mensagens enviadas após este ponto serão descartadas do histórico.
            </p>

            <div className="p-2.5 rounded-lg bg-[#0a0a0c] border border-mockbird-border/60 text-[11px] text-slate-300 font-mono line-clamp-3 select-text">
              “{rewindTarget.content}”
            </div>

            <div className="space-y-2 pt-1 border-t border-mockbird-border/60">
              <label className="flex items-start gap-2.5 text-[11px] text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={revertCodeOnRewind}
                  onChange={(e) => setRevertCodeOnRewind(e.target.checked)}
                  className="mt-0.5 rounded border-mockbird-border text-mockbird-blue focus:ring-0 cursor-pointer"
                />
                <div>
                  <span className="font-semibold text-white block">Reverter também o código da tela</span>
                  <span className="text-[10px] text-slate-400">Restaura o Canvas para o estado visual correspondente a este momento</span>
                </div>
              </label>

              {rewindTarget.isUser && (
                <label className="flex items-start gap-2.5 text-[11px] text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={reloadPromptOnRewind}
                    onChange={(e) => setReloadPromptOnRewind(e.target.checked)}
                    className="mt-0.5 rounded border-mockbird-border text-mockbird-blue focus:ring-0 cursor-pointer"
                  />
                  <div>
                    <span className="font-semibold text-white block">Carregar prompt para edição</span>
                    <span className="text-[10px] text-slate-400">Coloca o texto da mensagem na caixa de prompt para reenviar com ajustes</span>
                  </div>
                </label>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-mockbird-border/60">
              <button
                type="button"
                onClick={() => setRewindTarget(null)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white hover:bg-mockbird-card transition"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmRewind}
                className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-mockbird-blue hover:bg-mockbird-bluedark text-white flex items-center gap-1.5 transition shadow-md"
              >
                <RotateCcw size={13} />
                <span>Confirmar e Voltar</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
