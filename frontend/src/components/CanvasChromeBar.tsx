import React, { useEffect, useRef, useState } from 'react';
import { 
  ArrowLeft, 
  ArrowRight, 
  RotateCw, 
  Star, 
  Puzzle, 
  MoreVertical, 
  Plus, 
  X, 
  Globe, 
  SlidersHorizontal,
  Minus,
  Square
} from 'lucide-react';

export interface CanvasChromeBarProps {
  width: number;
  height: number;
  zoom: number;
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  onNavigate: (target: string, external?: boolean) => void;
  onReload: () => void;
  onViewportChange: (width: number, height: number) => void;
  onZoom: (zoom: number) => void;
  onFitToScreen?: () => void;
  navigationEvent?: { target: string; id: number };
  pageTitle?: string;
}

const DEVICES = {
  custom: { name: 'Responsive', width: 1440, height: 900 },
  desktop: { name: 'Desktop HD', width: 1440, height: 900 },
  desktop_small: { name: 'Laptop (1366×768)', width: 1366, height: 768 },
  tablet: { name: 'iPad Air (820×1180)', width: 820, height: 1180 },
  mobile_iphone16: { name: 'iPhone 16 (393×852)', width: 393, height: 852 },
  mobile: { name: 'Mobile (375×812)', width: 375, height: 812 },
  mobile_pixel: { name: 'Pixel 7 (412×915)', width: 412, height: 915 },
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
  onFitToScreen,
  navigationEvent,
  pageTitle = 'Mockbird Preview'
}: CanvasChromeBarProps) {
  const initialHistory: string[] = (() => {
    try {
      const saved = sessionStorage.getItem('mockbird-canvas-history');
      return saved ? (JSON.parse(saved) as string[]) : ['mockbird://tela'];
    } catch {
      return ['mockbird://tela'];
    }
  })();
  const historyRef = useRef<string[]>(initialHistory);
  const historyIndexRef = useRef(0);
  const [url, setUrl] = useState<string>(initialHistory[initialHistory.length - 1] || 'mockbird://tela');
  const [device, setDevice] = useState('desktop');
  const [network, setNetwork] = useState<NetworkProfile>('off');
  const [, setHistoryVersion] = useState(0);

  useEffect(() => {
    try {
      const savedIndex = sessionStorage.getItem('mockbird-canvas-history-index');
      if (savedIndex) {
        historyIndexRef.current = Math.min(
          historyRef.current.length - 1,
          Math.max(0, Number(savedIndex))
        );
      }
    } catch {
      // Ignora erro em contexto de sandbox
    }
    setUrl((current) => current || 'mockbird://tela');
  }, []);

  const persistHistory = () => {
    try {
      sessionStorage.setItem('mockbird-canvas-history', JSON.stringify(historyRef.current));
      sessionStorage.setItem('mockbird-canvas-history-index', String(historyIndexRef.current));
    } catch {
      // Ignora erro
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
    iframeRef.current?.contentWindow?.postMessage(
      {
        type: 'MOCKBIRD_DEVTOOLS_SET_THROTTLE',
        profile,
      },
      '*'
    );
  };

  return (
    <div
      data-testid="canvas-chrome-bar"
      className="flex flex-col rounded-t-xl bg-[#202124] text-slate-200 select-none overflow-hidden border border-[#3c4043] border-b-0 shadow-2xl"
      style={{ width: `${width}px` }}
    >
      {/* 1. Chrome Tab Strip (Abas do Navegador) */}
      <div className="h-9 bg-[#1f1f1f] flex items-center justify-between px-2 pt-1 border-b border-[#292a2d]">
        <div className="flex items-center gap-1 overflow-hidden max-w-[calc(100%-100px)]">
          {/* Aba Ativa do Google Chrome */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-t-lg bg-[#292a2d] text-white text-xs font-medium max-w-[220px] shadow-sm border-t border-x border-[#3c4043] relative group">
            <Globe size={13} className="text-[#8ab4f8] shrink-0" />
            <span className="truncate text-[11px] tracking-tight">{pageTitle}</span>
            <button
              type="button"
              className="p-0.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition"
              title="Fechar aba"
            >
              <X size={11} />
            </button>
          </div>

          {/* Botão de Nova Aba (+) */}
          <button
            type="button"
            className="p-1 rounded-full text-slate-400 hover:text-white hover:bg-white/10 transition"
            title="Nova guia"
          >
            <Plus size={14} />
          </button>
        </div>

        {/* Controles de Janela do Chrome */}
        <div className="flex items-center gap-2 text-slate-400 pr-1 shrink-0">
          <button type="button" className="p-1 hover:text-white transition" title="Minimizar">
            <Minus size={12} />
          </button>
          <button type="button" className="p-1 hover:text-white transition" title="Maximizar">
            <Square size={10} />
          </button>
          <button type="button" className="p-1 hover:text-rose-400 transition" title="Fechar">
            <X size={12} />
          </button>
        </div>
      </div>

      {/* 2. Chrome Omnibox & Navigation Bar */}
      <div className="h-10 bg-[#292a2d] px-3 flex items-center gap-2 border-b border-[#3c4043]">
        {/* Botões Voltar, Avançar, Recarregar */}
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            type="button"
            data-testid="chrome-back"
            aria-label="Voltar"
            disabled={historyIndexRef.current === 0}
            onClick={() => moveHistory(-1)}
            className="p-1.5 rounded-full text-slate-300 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent transition"
            title="Voltar"
          >
            <ArrowLeft size={14} />
          </button>
          <button
            type="button"
            data-testid="chrome-forward"
            aria-label="Avançar"
            disabled={historyIndexRef.current >= historyRef.current.length - 1}
            onClick={() => moveHistory(1)}
            className="p-1.5 rounded-full text-slate-300 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent transition"
            title="Avançar"
          >
            <ArrowRight size={14} />
          </button>
          <button
            type="button"
            data-testid="chrome-reload"
            aria-label="Recarregar"
            onClick={onReload}
            className="p-1.5 rounded-full text-slate-300 hover:text-white hover:bg-white/10 transition"
            title="Recarregar esta página"
          >
            <RotateCw size={14} />
          </button>
        </div>

        {/* Omnibox (Barra de URL estilo Chrome) */}
        <div className="flex-1 flex items-center bg-[#1e1f22] border border-[#3c4043] focus-within:border-[#8ab4f8] focus-within:bg-[#191a1c] rounded-full px-3 py-1 text-xs gap-2 transition">
          <SlidersHorizontal size={13} className="text-[#8ab4f8] shrink-0" />
          <input
            data-testid="chrome-url"
            role="searchbox"
            aria-label="URL"
            value={url}
            placeholder="mockbird://tela"
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') navigate(url);
            }}
            className="flex-1 bg-transparent text-slate-100 outline-none text-[12px] font-sans selection:bg-[#8ab4f8]/30 selection:text-white"
          />
          <button
            type="button"
            className="text-slate-400 hover:text-amber-400 transition"
            title="Adicionar aos favoritos"
          >
            <Star size={13} />
          </button>
        </div>

        {/* Ações da Direita do Chrome */}
        <div className="flex items-center gap-1 text-slate-300 shrink-0">
          <button
            type="button"
            className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition"
            title="Extensões"
          >
            <Puzzle size={14} />
          </button>
          <div
            className="w-6 h-6 rounded-full bg-[#8ab4f8]/20 text-[#8ab4f8] flex items-center justify-center font-bold text-[10px] border border-[#8ab4f8]/40"
            title="Conta Google"
          >
            M
          </div>
          <button
            type="button"
            className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition"
            title="Personalizar e controlar o Google Chrome"
          >
            <MoreVertical size={14} />
          </button>
        </div>
      </div>

      {/* 3. Chrome Device Mode Toolbar (Fiel à imagem 1 do usuário!) */}
      <div className="bg-[#20262d] border-b border-[#2d333b] px-3 py-1 flex flex-wrap items-center gap-2 text-xs text-[#9aa0a6] font-sans">
        <button type="button" className="p-0.5 text-slate-400 hover:text-white" title="Mais opções">
          <MoreVertical size={13} />
        </button>

        <span className="text-[11px] font-medium text-slate-400">Dimensions:</span>

        {/* Preset de Dispositivo */}
        <div className="relative">
          <select
            data-testid="chrome-device"
            aria-label="Dispositivo"
            value={device}
            onChange={(event) => selectDevice(event.target.value)}
            className="bg-[#161b22] border border-[#30363d] rounded px-2 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-[#58a6ff] cursor-pointer"
          >
            <option value="custom">Responsive</option>
            <option value="desktop">Desktop HD (1440×900)</option>
            <option value="desktop_small">Laptop (1366×768)</option>
            <option value="tablet">iPad Air (820×1180)</option>
            <option value="mobile_iphone16">iPhone 16 (393×852)</option>
            <option value="mobile">Mobile (375×812)</option>
            <option value="mobile_pixel">Pixel 7 (412×915)</option>
          </select>
        </div>

        {/* Dimensões Largura × Altura */}
        <div className="flex items-center gap-1 font-mono text-[11px]">
          <input
            data-testid="chrome-width"
            aria-label="Largura"
            type="number"
            min="1"
            value={width}
            onChange={(event) => {
              setDevice('custom');
              onViewportChange(Math.max(1, Number(event.target.value) || 1), height);
            }}
            className="w-14 bg-[#161b22] border border-[#30363d] rounded px-1.5 py-0.5 text-slate-200 text-center focus:outline-none focus:border-[#58a6ff]"
          />
          <span className="text-slate-500">×</span>
          <input
            data-testid="chrome-height"
            aria-label="Altura"
            type="number"
            min="1"
            value={height}
            onChange={(event) => {
              setDevice('custom');
              onViewportChange(width, Math.max(1, Number(event.target.value) || 1));
            }}
            className="w-14 bg-[#161b22] border border-[#30363d] rounded px-1.5 py-0.5 text-slate-200 text-center focus:outline-none focus:border-[#58a6ff]"
          />
        </div>

        {/* Zoom */}
        <select
          data-testid="chrome-zoom"
          aria-label="Zoom"
          value={zoom}
          onChange={(event) => {
            if (event.target.value === 'fit') {
              onFitToScreen?.();
            } else {
              onZoom(Number(event.target.value));
            }
          }}
          className="bg-[#161b22] border border-[#30363d] rounded px-2 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-[#58a6ff] cursor-pointer"
        >
          <option value="fit">Fit to window</option>
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => (
            <option key={value} value={value}>
              {Math.round(value * 100)}%
            </option>
          ))}
        </select>

        {/* Throttling de Rede */}
        <select
          data-testid="network-type"
          aria-label="Tipo de rede"
          value={network}
          onChange={(event) => updateNetwork(event.target.value as NetworkProfile)}
          className="bg-[#161b22] border border-[#30363d] rounded px-2 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-[#58a6ff] cursor-pointer"
        >
          <option value="off">No throttling</option>
          <option value="slow3g">Slow 3G</option>
          <option value="4g">4G</option>
        </select>

        {/* Save Data tag */}
        <span className="text-[11px] text-slate-400 hidden sm:inline">
          'Save-Data': default
        </span>

        {/* Botão de Rotacionar Dispositivo (Fiel ao ícone do Chrome DevTools na Imagem 2) */}
        <button
          type="button"
          data-testid="chrome-rotate"
          aria-label="Girar"
          onClick={() => onViewportChange(height, width)}
          className="p-1 rounded bg-[#161b22] border border-[#30363d] text-slate-300 hover:text-white hover:border-slate-500 transition ml-auto"
          title="Alternar orientação (Retrato / Paisagem)"
        >
          <RotateCw size={13} />
        </button>
      </div>

      {/* Réguas / Breakpoints do Chrome Device Mode */}
      <div className="h-2 bg-[#1c2126] border-b border-[#2d333b] flex items-center px-1 gap-1 opacity-70">
        <div className="flex-1 h-1 bg-[#30363d] rounded-sm"></div>
        <div className="w-16 h-1 bg-[#444c56] rounded-sm"></div>
        <div className="w-32 h-1 bg-[#30363d] rounded-sm"></div>
        <div className="flex-1 h-1 bg-[#30363d] rounded-sm"></div>
      </div>
    </div>
  );
}
