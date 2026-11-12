/**
 * Conexão WebSocket com a sala do projeto.
 *
 * Autenticação: o handshake usa o cookie de sessão (httpOnly), então o browser
 * precisa estar na mesma origem da API. Reconecta com backoff simples.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface Participant {
  user_id: string;
  name: string;
  color: string;
}

export interface RealtimeMessage {
  type: string;
  [key: string]: any;
}

export function useProjectSocket(
  projectId: string | undefined,
  onMessage?: (message: RealtimeMessage) => void
) {
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    if (!projectId) return;
    let disposed = false;
    let retry = 0;
    let reconnectTimer: number | undefined;

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${protocol}://${window.location.host}/api/ws/projects/${projectId}`);
      socketRef.current = ws;

      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };

      ws.onmessage = (event) => {
        let data: RealtimeMessage;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (data.type === 'presence') {
          setParticipants(Array.isArray(data.participants) ? data.participants : []);
          return;
        }
        if (data.type === 'ready') {
          if (Array.isArray(data.participants)) setParticipants(data.participants);
          return;
        }
        if (data.type === 'pong') return;
        handlerRef.current?.(data);
      };

      ws.onclose = () => {
        setConnected(false);
        setParticipants([]);
        if (disposed) return;
        retry = Math.min(retry + 1, 5);
        reconnectTimer = window.setTimeout(connect, retry * 1500);
      };

      ws.onerror = () => {
        // onclose cuida da reconexão.
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [projectId]);

  const send = useCallback((message: RealtimeMessage) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }, []);

  return { participants, connected, send };
}
