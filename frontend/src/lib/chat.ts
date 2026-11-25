/** Tipos e utilitários puros do painel de IA (sem React). */

export interface PlanItem {
  id: number;
  title: string;
  description: string;
  status?: 'pending' | 'running' | 'completed' | 'failed';
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

function htmlDensity(text: string): number {
  return (text.match(/<\/?[a-zA-Z][a-zA-Z0-9:-]*(?:\s[^<>]*)?>/g) || []).length;
}

/** Heurística de segurança: só devolve algo que parece marcação HTML. */
export function isRenderableHtml(html: string): boolean {
  const trimmed = (html || '').trim();
  if (!trimmed || !trimmed.includes('<') || !trimmed.includes('>')) return false;
  if (htmlDensity(trimmed) === 0) return false;
  // Documento sem nenhuma tag de fechamento é sinal de truncamento grave.
  return /<\/[a-zA-Z][^>]*>/.test(trimmed) || /<!doctype/i.test(trimmed) || htmlDensity(trimmed) > 2;
}

/**
 * Extrai o bloco HTML de uma resposta de LLM.
 *
 * Diferente da versão anterior, escolhe o bloco com MAIS marcação (não o
 * primeiro), aceita cerca não fechada (resposta truncada) e ignora texto de
 * raciocínio — evitando que prosa ou `reasoning_content` vire "HTML".
 */
export function cleanAndExtractHtml(text: string): string {
  if (!text) return '';

  const withoutThinking = text
    .replace(/<(think|thinking|reasoning)>[\s\S]*?<\/\1>/gi, '')
    .replace(/<(think|thinking|reasoning)>[\s\S]*$/i, '');

  const candidates: string[] = [];
  const fenceRe = /```[ \t]*[a-zA-Z0-9_-]*[ \t]*\r?\n?([\s\S]*?)(?:```|$)/g;
  let match: RegExpExecArray | null;
  while ((match = fenceRe.exec(withoutThinking)) !== null) {
    const body = (match[1] || '').trim();
    if (body.includes('<') && body.includes('>')) candidates.push(body);
    if (match.index === fenceRe.lastIndex) fenceRe.lastIndex++;
  }
  if (candidates.length > 0) {
    return candidates.sort((a, b) => (htmlDensity(b) - htmlDensity(a)) || (b.length - a.length))[0];
  }

  const docMatch = withoutThinking.match(/(<!DOCTYPE\s+html[\s\S]+?(?:<\/html>|$)|<html\b[\s\S]+?(?:<\/html>|$))/i);
  if (docMatch && htmlDensity(docMatch[1]) > 0) {
    return docMatch[1].replace(/```+$/, '').trim();
  }

  const tagMatch = withoutThinking.match(
    /<(?:div|section|main|header|footer|nav|article|aside|form|table|dialog|ul|ol|h[1-6]|p|button|a|img|input)\b[\s\S]*/i
  );
  if (tagMatch && htmlDensity(tagMatch[0]) > 0) {
    return tagMatch[0].replace(/```+$/, '').trim();
  }

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
