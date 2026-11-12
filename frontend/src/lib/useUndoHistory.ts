import { useCallback, useEffect, useRef, useState } from 'react';

const MAX_STEPS = 60;

interface UndoHistoryOptions<T> {
  /** Identifica o documento (ex: id da tela). Trocar a chave zera o histórico. */
  key: string;
  /** Valor atual do documento. Toda mudança vira um passo desfazível. */
  value: T;
  /** Aplica um valor ao documento (usado por desfazer/refazer). */
  onApply: (next: T) => void;
}

export interface UndoHistory {
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  /** Ignora a próxima mudança (ex: sincronização vinda de outro usuário). */
  markExternal: (next: unknown) => void;
}

/**
 * Histórico linear de desfazer/refazer sobre um valor controlado.
 *
 * Registra cada mudança que chega por `value`, inclusive as feitas dentro do
 * iframe do canvas, da IA ou do editor de código — todas passam pelo mesmo
 * estado da tela.
 */
export function useUndoHistory<T>({ key, value, onApply }: UndoHistoryOptions<T>): UndoHistory {
  const pastRef = useRef<T[]>([]);
  const futureRef = useRef<T[]>([]);
  const lastRef = useRef<T>(value);
  const keyRef = useRef<string>(key);
  const skipRef = useRef<unknown>(undefined);
  const [, setTick] = useState(0);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    if (keyRef.current !== key) {
      // Outra tela: histórico começa limpo.
      keyRef.current = key;
      pastRef.current = [];
      futureRef.current = [];
      lastRef.current = value;
      skipRef.current = undefined;
      refresh();
      return;
    }

    if (skipRef.current !== undefined && skipRef.current === value) {
      // Mudança externa (outro usuário, reversão): não entra no histórico.
      skipRef.current = undefined;
      lastRef.current = value;
      return;
    }
    if (value === lastRef.current) return;

    pastRef.current.push(lastRef.current);
    if (pastRef.current.length > MAX_STEPS) pastRef.current.shift();
    futureRef.current = [];
    lastRef.current = value;
    refresh();
  }, [key, value, refresh]);

  const markExternal = useCallback((next: unknown) => {
    skipRef.current = next;
  }, []);

  const undo = useCallback(() => {
    if (!pastRef.current.length) return;
    const next = pastRef.current.pop() as T;
    futureRef.current.push(lastRef.current);
    lastRef.current = next;
    skipRef.current = next;
    onApply(next);
    refresh();
  }, [onApply, refresh]);

  const redo = useCallback(() => {
    if (!futureRef.current.length) return;
    const next = futureRef.current.pop() as T;
    pastRef.current.push(lastRef.current);
    lastRef.current = next;
    skipRef.current = next;
    onApply(next);
    refresh();
  }, [onApply, refresh]);

  return {
    canUndo: pastRef.current.length > 0,
    canRedo: futureRef.current.length > 0,
    undo,
    redo,
    markExternal,
  };
}
