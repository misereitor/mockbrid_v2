import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, RotateCw } from 'lucide-react';

export interface CanvasChromeBarProps {
  width: number;
  height: number;
  zoom: number;
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  onNavigate: (target: string, external?: boolean) => void;
  onReload: () => void;
  onViewportChange: (width: number, height: number) => void;
  onZoom: (zoom: number) => void;
  navigationEvent?: { target: string; id: number };
}

const DEVICES = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 768, height: 1024 },
  mobile: { width: 375, height: 812 },
} as const;

type NetworkProfile = 'off' | 'slow3g' | '4g';

export function CanvasChromeBar({
  width,
  height,
  zoom,
  iframeRef,
  onNavigate,
  onReload,
  onViewportChange,
  onZoom,
  navigationEvent,
}: CanvasChromeBarProps) {
  const initialHistory: string[] = (() => {
    try {
      const saved = sessionStorage.getItem('mockbird-canvas-history');
      return saved ? JSON.parse(saved) as string[] : ['mockbird://tela'];
    } catch {
      return ['mockbird://tela'];
    }
  })();
  const historyRef = useRef<string[]>(initialHistory);
  const historyIndexRef = useRef(0);
  const [url, setUrl] = useState<string>(initialHistory[initialHistory.length - 1] || 'mockbird://tela');
  const [device, setDevice] = useState('custom');
  const [network, setNetwork] = useState<NetworkProfile>('off');
  const [, setHistoryVersion] = useState(0);

  useEffect(() => {
    try {
      const savedIndex = sessionStorage.getItem('mockbird-canvas-history-index');
      if (savedIndex) historyIndexRef.current = Math.min(historyRef.current.length - 1, Math.max(0, Number(savedIndex)));
    } catch {
      // Session storage is optional in embedded or privacy-restricted contexts.
    }
    setUrl((current) => current || 'mockbird://tela');
  }, []);

  const persistHistory = () => {
    try {
      sessionStorage.setItem('mockbird-canvas-history', JSON.stringify(historyRef.current));
      sessionStorage.setItem('mockbird-canvas-history-index', String(historyIndexRef.current));
    } catch {
      // Session storage is optional in embedded or privacy-restricted contexts.
    }
  };

  useEffect(() => {
    if (navigationEvent) {
      const history = historyRef.current.slice(0, historyIndexRef.current + 1);
      history.push(navigationEvent.target);
      historyRef.current = history;
      historyIndexRef.current = history.length - 1;
      setUrl(navigationEvent.target);
      setHistoryVersion((version) => version + 1);
    }
  }, [navigationEvent]);

  const navigate = (target: string) => {
    const value = target.trim();
    if (!value) return;
    const history = historyRef.current.slice(0, historyIndexRef.current + 1);
    history.push(value);
    historyRef.current = history;
    historyIndexRef.current = history.length - 1;
    setUrl(value);
    setHistoryVersion((version) => version + 1);
    persistHistory();
    onNavigate(value);
  };

  const moveHistory = (delta: -1 | 1) => {
    const next = historyIndexRef.current + delta;
    if (next < 0 || next >= historyRef.current.length) return;
    historyIndexRef.current = next;
    const target = historyRef.current[next];
    setUrl(target);
    setHistoryVersion((version) => version + 1);
    persistHistory();
    onNavigate(target);
  };

  const selectDevice = (value: string) => {
    setDevice(value);
    if (value in DEVICES) {
      const preset = DEVICES[value as keyof typeof DEVICES];
      onViewportChange(preset.width, preset.height);
    }
  };

  const updateNetwork = (profile: NetworkProfile) => {
    setNetwork(profile);
    iframeRef.current?.contentWindow?.postMessage({
      type: 'MOCKBIRD_DEVTOOLS_SET_THROTTLE',
      profile,
    }, '*');
  };

  return (
    <div
      data-testid="canvas-chrome-bar"
      className="flex flex-wrap items-center gap-1 p-1.5 rounded-t-xl bg-mockbird-surface border-x border-t border-mockbird-border text-xs select-none"
      style={{ width: `${width}px` }}
    >
      <button type="button" data-testid="chrome-back" aria-label="Voltar" disabled={historyIndexRef.current === 0} onClick={() => moveHistory(-1)} className="mb-btn-ghost !p-1.5 disabled:opacity-40"><ArrowLeft size={14} /></button>
      <button type="button" data-testid="chrome-forward" aria-label="Avançar" disabled={historyIndexRef.current >= historyRef.current.length - 1} onClick={() => moveHistory(1)} className="mb-btn-ghost !p-1.5 disabled:opacity-40"><ArrowRight size={14} /></button>
      <button type="button" data-testid="chrome-reload" aria-label="Recarregar" onClick={onReload} className="mb-btn-ghost !p-1.5"><RotateCw size={14} /></button>
      <input
        data-testid="chrome-url"
        role="searchbox"
        aria-label="URL"
        value={url}
        placeholder="mockbird://tela"
        onChange={(event) => setUrl(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter') navigate(url); }}
        className="min-w-[150px] flex-1 rounded border border-mockbird-border bg-mockbird-bg px-2 py-1 text-slate-200 outline-none"
      />
      <select data-testid="chrome-device" aria-label="Dispositivo" value={device} onChange={(event) => selectDevice(event.target.value)} className="rounded border border-mockbird-border bg-mockbird-bg px-1.5 py-1 text-slate-200">
        <option value="custom">Personalizado</option>
        <option value="desktop">Desktop 1440×900</option>
        <option value="tablet">Tablet 768×1024</option>
        <option value="mobile">Mobile 375×812</option>
      </select>
      <input data-testid="chrome-width" aria-label="Largura" type="number" min="1" value={width} onChange={(event) => { setDevice('custom'); onViewportChange(Math.max(1, Number(event.target.value) || 1), height); }} className="w-16 rounded border border-mockbird-border bg-mockbird-bg px-1 py-1 text-slate-200" />
      <input data-testid="chrome-height" aria-label="Altura" type="number" min="1" value={height} onChange={(event) => { setDevice('custom'); onViewportChange(width, Math.max(1, Number(event.target.value) || 1)); }} className="w-16 rounded border border-mockbird-border bg-mockbird-bg px-1 py-1 text-slate-200" />
      <button type="button" data-testid="chrome-rotate" aria-label="Girar" onClick={() => onViewportChange(height, width)} className="mb-btn-ghost !p-1.5">↔</button>
      <select data-testid="chrome-zoom" aria-label="Zoom" value={zoom} onChange={(event) => onZoom(Number(event.target.value))} className="rounded border border-mockbird-border bg-mockbird-bg px-1.5 py-1 text-slate-200">
        {[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{Math.round(value * 100)}%</option>)}
      </select>
      <select data-testid="network-type" aria-label="Tipo de rede" value={network} onChange={(event) => updateNetwork(event.target.value as NetworkProfile)} className="rounded border border-mockbird-border bg-mockbird-bg px-1.5 py-1 text-slate-200">
        <option value="off">Sem rede</option>
        <option value="slow3g">Slow 3G</option>
        <option value="4g">4G</option>
      </select>
    </div>
  );
}
