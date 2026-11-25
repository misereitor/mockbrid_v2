import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, 
  Loader2, 
  AlertCircle, 
  ChevronDown, 
  ChevronUp, 
  Brain, 
  Plus, 
  Trash2, 
  History, 
  MessageSquare, 
  CheckCircle2, 
  Workflow, 
  ShieldCheck, 
  Wrench, 
  Zap, 
  ListTodo,
  RotateCcw,
  Undo2,
  Redo2
} from 'lucide-react';
import { SelectedElementInfo } from './CanvasEditor';
import {
  cleanAndExtractHtml,
  computeDiffLines,
  isRenderableHtml,
  type ChatMessage,
  type ChatSession,
  type DiffLine,
  type PlanItem,
  type QualityAuditInfo,
} from './lib/chat';
import { DiffViewer } from './components/chat/DiffViewer';
import { ChatComposer } from './components/chat/ChatComposer';
import { RewindModal, type RewindTarget } from './components/chat/RewindModal';

export type { ChatMessage, ChatSession, DiffLine, PlanItem, QualityAuditInfo };
export { cleanAndExtractHtml, computeDiffLines };

const createDefaultSession = (): ChatSession => ({
  id: `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  title: 'Conversa Inicial',
  createdAt: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
  messages: []
});

const readStoredSessions = (key: string): ChatSession[] | null => {
  try {
    const saved = localStorage.getItem(key);
    if (!saved) return null;
    const parsed = JSON.parse(saved);
    if (Array.isArray(parsed) && parsed.length > 0) return parsed as ChatSession[];
  } catch (e) {
    console.error('Falha ao carregar sessões de chat:', e);
  }
  return null;
};

interface AIChatPanelProps {
  currentHtml: string;
  onApplyHtml: (newHtml: string) => void;
  onApplyElementPatch?: (newHtml: string, target?: { mbId?: string; selector?: string }) => void;
  selectedElement?: SelectedElementInfo | null;
  onClearSelectedElement?: () => void;
  initialPrompt?: string;
  onClose?: () => void;
  projectId?: string;
  screenId?: string;
  onCaptureScreenshot?: () => Promise<string>;
}

export function AIChatPanel({ 
  currentHtml, 
  onApplyHtml, 
  onApplyElementPatch,
  selectedElement,
  onClearSelectedElement,
  initialPrompt, 
  projectId = 'default',
  screenId
}: AIChatPanelProps) {
  const storageKey = `mockbird_chat_sessions_${projectId}`;
  // Hidrata direto do localStorage no primeiro render: se um efeito fizesse
  // isso depois, o efeito de persistência gravaria o estado vazio por cima do
  // histórico salvo (o StrictMode monta os efeitos duas vezes).
  const [sessions, setSessions] = useState<ChatSession[]>(() => readStoredSessions(storageKey) || [createDefaultSession()]);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => sessions[0]?.id || 'sess_default');
  const [prompt, setPrompt] = useState(initialPrompt || '');
  const [loading, setLoading] = useState(false);
  // A conversa é sempre automática: o agente decide internamente se deve
  // explicar, inspecionar, editar ou gerar código.
  const executionMode: 'agent' = 'agent';

  // Estados do Agente Autônomo
  const [agentStep, setAgentStep] = useState<{ node: string; title: string; detail: string } | null>(null);
  const [agentTimeline, setAgentTimeline] = useState<Array<{ node: string; title: string; detail?: string; status: string }>>([]);
  const [agentPlan, setAgentPlan] = useState<PlanItem[]>([]);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [agentAudit, setAgentAudit] = useState<QualityAuditInfo | null>(null);

  // Estado transitório do streaming
  const [streamingThought, setStreamingThought] = useState('');
  const [streamingContent, setStreamingContent] = useState('');
  const [showThought, setShowThought] = useState(false);

  // Diff e Reversão
  const [openDiffMsgId, setOpenDiffMsgId] = useState<string | null>(null);
  const [diffTabs, setDiffTabs] = useState<Record<string, 'unified' | 'split'>>({});
  
  // Modal de Rollback / Voltar Mensagem (estilo Antigravity)
  const [rewindTarget, setRewindTarget] = useState<RewindTarget | null>(null);
  const [revertCodeOnRewind, setRevertCodeOnRewind] = useState<boolean>(true);
  const [reloadPromptOnRewind, setReloadPromptOnRewind] = useState<boolean>(true);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const lastPromptRef = useRef<string>('');
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
  const [providerInfo, setProviderInfo] = useState<{ provider_type: string; base_url?: string; is_active?: boolean; tokens_used_month?: number; monthly_token_limit?: number } | null>(null);
  const [usageInfo, setUsageInfo] = useState<{ tokens_used_month: number; monthly_token_limit: number; plan?: { name?: string } | null } | null>(null);
  const [providerLoading, setProviderLoading] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const thoughtEndRef = useRef<HTMLDivElement>(null);
  const hydratedKeyRef = useRef(storageKey);

  // Troca de projeto no mesmo painel: recarrega a conversa daquela chave.
  useEffect(() => {
    if (hydratedKeyRef.current === storageKey) return;
    hydratedKeyRef.current = storageKey;
    const stored = readStoredSessions(storageKey);
    const next = stored || [createDefaultSession()];
    setSessions(next);
    setCurrentSessionId(next[0].id);
    setStreamingContent('');
    setStreamingThought('');
    setAgentStep(null);
    setAgentTimeline([]);
    setAgentPlan([]);
    setAgentAudit(null);
    setErrorMessage(null);
  }, [storageKey]);

  // Persiste sessões no localStorage, mas nunca antes de a chave atual estar
  // hidratada — assim o estado vazio inicial não apaga o histórico.
  useEffect(() => {
    if (hydratedKeyRef.current !== storageKey) return;
    if (sessions.length === 0) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(sessions));
    } catch (e) {
      console.error('Erro ao persistir sessões:', e);
    }
  }, [sessions, storageKey]);

  // Sincroniza initialPrompt externo
  useEffect(() => {
    if (initialPrompt) {
      setPrompt(initialPrompt);
    }
  }, [initialPrompt]);

  // Busca configuração real do provedor e consumo da organização.
  useEffect(() => {
    setProviderLoading(true);
    Promise.all([fetch('/api/ai/providers'), fetch('/api/org/ai-usage')])
      .then(async ([providersResponse, usageResponse]) => {
        if (providersResponse.ok) {
          const data = await providersResponse.json();
          if (Array.isArray(data) && data.length > 0) {
            const active = data.find((item: { is_active?: boolean }) => item.is_active) || data[0];
            setProviderInfo(active);
            if (active.custom_models?.length) setAvailableModels(active.custom_models);
            if (active.default_model) setSelectedModel(active.default_model);
          }
        }
        if (usageResponse.ok) setUsageInfo(await usageResponse.json());
      })
      .catch(console.error)
      .finally(() => setProviderLoading(false));
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
    setAgentTimeline([]);
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
  const handleSendMessage = async (e?: React.FormEvent, overridePrompt?: string) => {
    if (e) e.preventDefault();
    const cleanPrompt = (overridePrompt ?? prompt).trim();
    if (!cleanPrompt || loading) return;
    lastPromptRef.current = cleanPrompt;

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

    // FLUXO 1: AGENTE AUTÔNOMO
    if (executionMode === 'agent') {
      try {
        const response = await fetch('/api/ai/agent/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: cleanPrompt,
            current_html: currentHtml,
            project_id: projectId,
            screen_id: screenId,
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
        let validationFailure = '';

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
                setAgentTimeline(prev => [...prev, { node: ev.node, title: ev.title, detail: ev.detail, status: 'running' }]);
              } else if (ev.type === 'node_end') {
                setAgentTimeline(prev => prev.map(item => item.node === ev.node ? { ...item, status: ev.status || 'completed' } : item));
              } else if (ev.type === 'node_progress') {
                if (ev.detail && agentStep) {
                  setAgentStep({ ...agentStep, detail: ev.detail });
                }
              } else if (ev.type === 'plan_ready') {
                collectedPlan = ev.plan || [];
                setAgentPlan(collectedPlan);
              } else if (ev.type === 'plan') {
                collectedPlan = ev.plan || [];
                setAgentPlan(collectedPlan);
              } else if (ev.type === 'tool_call') {
                setActiveTool(ev.tool);
              } else if (ev.type === 'tool_result') {
                setActiveTool(null);
              } else if (ev.type === 'content_chunk') {
                setStreamingContent(prev => prev + (ev.text || ''));
              } else if (ev.type === 'audit_result') {
                collectedAudit = {
                  score: ev.score,
                  passed: ev.passed,
                  issues: ev.issues || [],
                  suggestions: ev.suggestions || []
                };
                setAgentAudit(collectedAudit);
              } else if (ev.type === 'validation_result') {
                if (!ev.ok && ev.errors && ev.errors.length > 0) {
                  validationFailure = `Validação (${ev.scope || 'patch'}): ${ev.errors.slice(0, 3).join('; ')}`;
                }
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
        const hasValidPatch = isRenderableHtml(effectivePatch);
        if (!hasValidPatch && validationFailure) {
          setErrorMessage(prev => prev || validationFailure);
        }
        const nowTime = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

        // Auto-aplicação imediata no Canvas quando o Agente produz um patch de código válido
        if (hasValidPatch) {
          try {
            if (finalPatchType === 'element' && onApplyElementPatch) {
              onApplyElementPatch(effectivePatch, {
                mbId: finalTargetMbId,
                selector: finalTargetSelector
              });
            } else {
              onApplyHtml(effectivePatch);
            }
            if (onClearSelectedElement) {
              onClearSelectedElement();
            }
          } catch (e) {
            console.error('Erro ao auto-aplicar patch no Canvas:', e);
          }
        }

        const assistantMessage: ChatMessage = {
          id: `msg_asst_${Date.now()}`,
          role: 'assistant',
          content: finalSummary || (hasValidPatch ? 'Interface construída e aplicada diretamente no Canvas.' : 'Instrução processada pelo Agente.'),
          reasoning: finalReasoning.trim() || undefined,
          patch: hasValidPatch ? effectivePatch : undefined,
          patchType: hasValidPatch ? finalPatchType : 'none',
          targetSelector: finalTargetSelector,
          targetMbId: finalTargetMbId,
          targetTag: finalTargetTag,
          mode: 'agent',
          plan: collectedPlan.length > 0 ? collectedPlan : undefined,
          audit: collectedAudit || undefined,
          htmlSnapshotBefore: currentSnapshot,
          elementSnapshotBefore: selectedElement?.snippet,
          isApplied: hasValidPatch,
          appliedAt: hasValidPatch ? nowTime : undefined,
          htmlSnapshotAfter: hasValidPatch ? effectivePatch : undefined,
          timestamp: nowTime
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
    let chatValidationFailure = '';

    try {
      const response = await fetch('/api/ai/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: cleanPrompt,
          current_html: currentHtml,
          project_id: projectId,
          screen_id: screenId,
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
            } else if (ev.type === 'validation_result') {
              if (!ev.ok && ev.errors && ev.errors.length > 0) {
                chatValidationFailure = `Validação: ${ev.errors.slice(0, 3).join('; ')}`;
              }
            } else if (ev.type === 'error') {
              setErrorMessage(ev.detail || 'Ocorreu um erro durante a inferência.');
            }
          } catch {
            // chunk parcial
          }
        }
      }

      const extracted = cleanAndExtractHtml(finalPatchFromServer || accumulatedContent);
      const effectivePatch = isRenderableHtml(extracted) ? extracted : '';
      if (!effectivePatch && chatValidationFailure) {
        setErrorMessage(prev => prev || chatValidationFailure);
      }
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

  const estimatedContextTokens = Math.ceil((currentHtml.length + prompt.length) / 4);
  const responseLimit = 8192;
  const usagePercent = usageInfo?.monthly_token_limit
    ? Math.min(100, Math.round((usageInfo.tokens_used_month / usageInfo.monthly_token_limit) * 100))
    : 0;
  const providerLabel = providerInfo?.provider_type || (providerLoading ? 'conectando' : 'não configurado');
  const compactNumber = (value?: number) => value == null ? '—' : new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(value);

  return (
    <div className="w-full flex flex-col h-full bg-[#0b0c10] text-slate-100 select-none overflow-hidden relative">
      {/* Header com Seletor de Modelo e Histórico */}
      <div className="px-4 py-3 border-b border-white/[0.08] flex items-center justify-between gap-3 shrink-0 bg-[#11131b]">
        <div className="flex items-center gap-2 min-w-0">
          <div className="relative p-2 rounded-xl bg-[#1a2030] text-cyan-300 shrink-0 border border-cyan-300/15">
            <Workflow size={17} />
            <span className="absolute -right-0.5 -bottom-0.5 h-2 w-2 rounded-full bg-emerald-400 ring-2 ring-[#11131d]" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[13px] font-semibold tracking-tight text-white truncate">Agente Autônomo</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded-md font-medium bg-emerald-400/10 text-emerald-300">online</span>
            </div>
            <p className="text-[10px] text-slate-400 truncate">Analisa, executa e valida alterações no canvas</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowSessionsDrawer(!showSessionsDrawer)}
              className={`p-2 rounded-lg border transition-all text-xs flex items-center gap-1.5 ${
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
              className="p-2 rounded-lg bg-white/[0.03] border border-white/[0.08] hover:bg-white/[0.08] text-slate-300 hover:text-white transition"
            title="Nova Conversa"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* O agente escolhe o fluxo automaticamente; não há modo manual. */}
      <div className="px-4 py-1.5 bg-[#0d0f15] border-b border-white/[0.06] flex items-center justify-end text-xs">

        {/* Modelo Selecionado */}
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="bg-transparent border-0 rounded-md px-1.5 py-0.5 text-[10px] text-slate-500 focus:outline-none focus:text-slate-200 cursor-pointer"
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
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3 text-xs scrollbar-thin scrollbar-thumb-white/10">
        {currentMessages.length === 0 && !loading && (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-400 space-y-4">
          <div className="relative p-3.5 rounded-2xl bg-[#151b2a] text-cyan-300 border border-cyan-300/15">
              <Workflow size={30} />
              <Sparkles size={13} className="absolute -right-1 -top-1 text-indigo-300" />
            </div>
            <div className="space-y-1">
              <h4 className="text-sm font-semibold text-white tracking-tight">Como posso melhorar sua tela?</h4>
              <p className="text-[11px] text-slate-400 max-w-[260px] leading-relaxed">
                Descreva a mudança em linguagem natural. Eu inspeciono o canvas, faço a alteração e valido o resultado.
              </p>
            </div>

            {/* Sugestões rápidas de prompt */}
            <div className="pt-2 w-full max-w-[260px] space-y-1.5 text-left">
              <button
                type="button"
                onClick={() => setPrompt('Cria uma landing page para concessionária Honda com hero do Civic Type R, grid bento de modelos e simulador de financiamento')}
                 className="w-full p-2.5 rounded-lg bg-[#11131b] hover:bg-[#181b26] border border-white/[0.08] text-[11px] text-slate-300 transition text-left"
              >
                🏎️ Concessionária Honda com Bento Grid
              </button>
              <button
                type="button"
                onClick={() => setPrompt('O layout tá com alinhamento quebrado no cabeçalho e nos cards. Poderia consertar a estrutura mantendo os elementos?')}
                 className="w-full p-2.5 rounded-lg bg-[#11131b] hover:bg-[#181b26] border border-white/[0.08] text-[11px] text-slate-300 transition text-left"
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
                      <span>{msg.mode === 'agent' ? 'Agente' : 'Chat Direto'}</span>
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
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-bold text-white flex items-center gap-1.5">
                      <Sparkles size={14} className="text-mockbird-cyan shrink-0" />
                      {msg.patchType === 'element'
                        ? `Alteração Cirúrgica <${msg.targetTag || 'alvo'}>`
                        : `Versão da Tela (${msg.timestamp})`}
                    </span>
                  </div>

                  {msg.patchType === 'element' && (msg.targetSelector || msg.targetMbId) && (
                    <div className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                      <span>Alvo:</span>
                      <span className="text-emerald-300 font-semibold">{msg.targetSelector || `#${msg.targetMbId}`}</span>
                    </div>
                  )}

                  <DiffViewer
                    message={msg}
                    diffLines={diffLines}
                    addedCount={addedCount}
                    removedCount={removedCount}
                    isOpen={isDiffOpen}
                    tab={currentDiffTab}
                    onTabChange={(tab) => setDiffTabs(prev => ({ ...prev, [msg.id]: tab }))}
                    onToggle={() => setOpenDiffMsgId(isDiffOpen ? null : msg.id)}
                    onCopy={handleCopyCode}
                    copiedId={copiedId}
                  />

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

        {/* Execução Ativa do Agente Autônomo */}
        {loading && executionMode === 'agent' && (
          <div className="space-y-2.5 max-w-[96%] animate-in fade-in">
            {/* Card do Nó Ativo */}
            <div className="p-3 rounded-xl bg-[#151827] border border-indigo-400/20 text-xs space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-indigo-300 font-bold">
                  <Loader2 size={14} className="animate-spin text-mockbird-cyan" />
                  <span className="text-white">{agentStep?.title || 'Inicializando agente...'}</span>
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

            {agentTimeline.length > 0 && (
              <div className="p-3 rounded-xl border border-white/[0.08] bg-[#11131b] space-y-2">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-mockbird-cyan"><Workflow size={13} /><span>Linha do tempo</span></div>
                {agentTimeline.map((item, index) => (
                  <div key={`${item.node}-${index}`} className="flex items-center gap-2 text-[10px] text-slate-300">
                    <span className={`h-2 w-2 rounded-full ${item.status === 'running' ? 'bg-cyan-400 animate-pulse' : item.status === 'failed' ? 'bg-red-400' : 'bg-emerald-400'}`} />
                    <span>{item.title}</span>
                    <span className="ml-auto text-slate-500">{item.status === 'running' ? 'executando' : item.status === 'failed' ? 'falhou' : 'concluído'}</span>
                  </div>
                ))}
              </div>
            )}
            {/* Plano de Ação em Andamento */}
            {agentPlan.length > 0 && (
              <div className="p-3 rounded-xl border border-white/[0.08] bg-[#11131b] space-y-2">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-mockbird-cyan">
                  <Workflow size={13} />
                  <span>Plano Arquitetural ({agentPlan.length} etapas)</span>
                </div>
                <div className="space-y-1">
                  {agentPlan.map((p) => (
                    <div key={p.id} className="flex items-start gap-2 text-[10px] text-slate-300 bg-mockbird-surface p-1.5 rounded-lg border border-mockbird-border/40">
                       <span className={`font-mono font-bold shrink-0 ${p.status === 'completed' ? 'text-emerald-400' : p.status === 'failed' ? 'text-red-400' : 'text-mockbird-cyan'}`}>{p.status === 'completed' ? '✓' : p.status === 'failed' ? '!' : `${p.id}.`}</span>
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
        {loading && false && (
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
              {lastPromptRef.current && (
                <button
                  type="button"
                  onClick={() => handleSendMessage(undefined, lastPromptRef.current)}
                  disabled={loading}
                  className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-rose-200 hover:text-white underline underline-offset-2 disabled:opacity-50"
                >
                  <RotateCcw size={11} /> Tentar novamente
                </button>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <ChatComposer
        prompt={prompt}
        onPromptChange={setPrompt}
        onSubmit={handleSendMessage}
        loading={loading}
        executionMode={executionMode}
        selectedElement={selectedElement}
        onClearSelectedElement={onClearSelectedElement}
      />

      <div className="shrink-0 border-t border-white/[0.06] bg-[#090b10] px-3 py-1.5 font-mono text-[9px] text-slate-500">
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap">
          <span className="flex items-center gap-1 text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${providerLoading ? 'bg-amber-400' : providerInfo ? 'bg-emerald-400' : 'bg-rose-400'}`} />{providerLabel}</span>
          <span className="text-slate-300">{selectedModel}</span>
          <span title="Estimativa: caracteres divididos por 4">ctx ~{compactNumber(estimatedContextTokens)} / {compactNumber(responseLimit)}</span>
          <span className="ml-auto flex items-center gap-1.5" title="Consumo mensal da organização">
            uso {compactNumber(usageInfo?.tokens_used_month)} / {compactNumber(usageInfo?.monthly_token_limit)}
            {usageInfo?.monthly_token_limit ? <span className="h-1 w-12 overflow-hidden rounded-full bg-white/10"><span className="block h-full bg-cyan-400" style={{ width: `${usagePercent}%` }} /></span> : null}
          </span>
        </div>
      </div>

      {rewindTarget && (
        <RewindModal
          target={rewindTarget}
          revertCode={revertCodeOnRewind}
          onRevertCodeChange={setRevertCodeOnRewind}
          reloadPrompt={reloadPromptOnRewind}
          onReloadPromptChange={setReloadPromptOnRewind}
          onCancel={() => setRewindTarget(null)}
          onConfirm={handleConfirmRewind}
        />
      )}
    </div>
  );
}
