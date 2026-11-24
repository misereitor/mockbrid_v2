import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { 
  ArrowLeft, 
  Bell, 
  Lock, 
  MessageSquare, 
  Send, 
  X, 
  Sun, 
  Moon, 
  RotateCcw, 
  ChevronDown, 
  Settings2, 
  Maximize2, 
  Minimize2,
  MoreVertical,
  RotateCw
} from 'lucide-react';
import { resolveScreenIndex } from '../lib/mockNav';
import { applyThemeToHtml } from '../lib/canvasDoc';

interface GuestComment {
  id: string;
  screen_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

interface PresentationPageProps {
  slug: string;
  onBackToApp?: () => void;
}

export const PresentationPage: React.FC<PresentationPageProps> = ({ slug, onBackToApp }) => {
  const [projectData, setProjectData] = useState<any>(null);
  const [currentScreenIndex, setCurrentScreenIndex] = useState(0);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [needsPassword, setNeedsPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [presentationTheme, setPresentationTheme] = useState<'dark' | 'light'>('dark');
  const [currentScenarioIndex, setCurrentScenarioIndex] = useState(0);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Estados de Responsividade e Device Mode na Apresentação (Fiel ao Chrome DevTools)
  const PRESENTATION_DEVICES: Record<string, { name: string; width: number; height: number }> = {
    responsive: { name: 'Responsive', width: 0, height: 0 },
    iphone16: { name: 'iPhone 16', width: 393, height: 852 },
    iphone14pro: { name: 'iPhone 14 Pro', width: 393, height: 852 },
    pixel7: { name: 'Pixel 7', width: 412, height: 915 },
    ipad_air: { name: 'iPad Air', width: 820, height: 1180 },
    desktop: { name: 'Desktop HD', width: 1440, height: 900 },
    laptop: { name: 'Laptop', width: 1366, height: 768 },
  };

  const [deviceKey, setDeviceKey] = useState<string>('responsive');
  const [deviceWidth, setDeviceWidth] = useState<number>(393);
  const [deviceHeight, setDeviceHeight] = useState<number>(852);
  const [zoomScale, setZoomScale] = useState<'fit' | number>('fit');
  const [isLandscape, setIsLandscape] = useState(false);
  const [throttle, setThrottle] = useState<'off' | 'slow3g' | '4g'>('off');

  const viewportContainerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 1200, height: 800 });

  useEffect(() => {
    const el = viewportContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleDeviceSelect = (key: string) => {
    setDeviceKey(key);
    if (key !== 'responsive' && PRESENTATION_DEVICES[key]) {
      const d = PRESENTATION_DEVICES[key];
      setDeviceWidth(d.width);
      setDeviceHeight(d.height);
    }
  };

  const activeWidth = isLandscape ? deviceHeight : deviceWidth;
  const activeHeight = isLandscape ? deviceWidth : deviceHeight;

  const currentScale = useMemo(() => {
    if (deviceKey === 'responsive') return 1;
    if (zoomScale !== 'fit') return zoomScale;
    const paddingX = 48;
    const paddingY = 48;
    const availW = Math.max(containerSize.width - paddingX, 200);
    const availH = Math.max(containerSize.height - paddingY, 200);
    const scaleW = availW / activeWidth;
    const scaleH = availH / activeHeight;
    return Math.min(1, Math.min(scaleW, scaleH));
  }, [deviceKey, zoomScale, containerSize, activeWidth, activeHeight]);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  useEffect(() => {
    const handleFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', handleFsChange);
    return () => document.removeEventListener('fullscreenchange', handleFsChange);
  }, []);

  // Comentários de visitantes (share links com allow_comments)
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [comments, setComments] = useState<GuestComment[]>([]);
  const [guestName, setGuestName] = useState('');
  const [commentBody, setCommentBody] = useState('');
  const [commentError, setCommentError] = useState<string | null>(null);
  const [sendingComment, setSendingComment] = useState(false);

  const loadPresentation = useCallback((pwd?: string) => {
    setLoading(true);
    const query = pwd ? `?password=${encodeURIComponent(pwd)}` : '';
    return fetch(`/api/public/p/${slug}${query}`)
      .then(async r => {
        if (r.status === 401 || r.status === 403) {
          setNeedsPassword(true);
          setPasswordError(r.status === 403 ? 'Senha incorreta.' : null);
          setLoading(false);
          return null;
        }
        if (!r.ok) throw new Error('Projeto de apresentação não encontrado');
        return r.json();
      })
      .then(d => {
        if (!d) return;
        setNeedsPassword(false);
        setProjectData(d);
        // Encontra tela principal se houver
        if (d.screens && d.screens.length > 0) {
          const mainIdx = d.screens.findIndex((s: any) => s.is_main);
          if (mainIdx >= 0) setCurrentScreenIndex(mainIdx);
        }
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    loadPresentation();
  }, [loadPresentation]);

  // Listener para eventos interativos no iframe
  useEffect(() => {
    const handleMsg = (ev: MessageEvent) => {
      if (ev.source !== iframeRef.current?.contentWindow) return;
      if (ev.data?.type === 'MOCK_TOAST' || ev.data?.type === 'MOCKBIRD_TOAST') {
        setToastMessage(ev.data.message);
        setTimeout(() => setToastMessage(null), 3500);
      } else if (ev.data?.type === 'MOCKBIRD_NAVIGATE') {
        const target = String(ev.data.target || '');
        const screens = projectData?.screens || [];
        const idx = resolveScreenIndex(target, screens);
        if (idx >= 0) {
          setCurrentScreenIndex(idx);
        }
      }
    };
    window.addEventListener('message', handleMsg);
    return () => window.removeEventListener('message', handleMsg);
  }, [projectData?.screens]);

  // Injeta HTML e scripts interativos na tela do CEO
  const activeScreen = projectData?.screens?.[currentScreenIndex];
  const commentsEnabled = Boolean(projectData?.allow_comments);
  const screenId = activeScreen?.id as string | undefined;

  // Resolve tokens com suporte a light/dark e shared
  const resolvedTokens = useMemo(() => {
    const t = projectData?.tokens || {};
    if (t.light || t.dark || t.shared) {
      const themeTokens = presentationTheme === 'light' ? (t.light || {}) : (t.dark || {});
      return { ...(t.shared || {}), ...themeTokens };
    }
    return t;
  }, [projectData?.tokens, presentationTheme]);

  useEffect(() => {
    if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({
        type: 'MOCKBIRD_SET_THEME',
        theme: presentationTheme,
        tokens: resolvedTokens,
      }, '*');
    }
  }, [presentationTheme, resolvedTokens]);

  const loadComments = useCallback(async () => {
    if (!commentsEnabled || !screenId) return;
    const pwdQuery = password ? `&password=${encodeURIComponent(password)}` : '';
    try {
      const res = await fetch(`/api/public/p/${slug}/comments?screen_id=${screenId}${pwdQuery}`);
      if (res.ok) setComments(await res.json());
    } catch (err) {
      console.error('Erro ao carregar comentários:', err);
    }
  }, [commentsEnabled, screenId, slug, password]);

  useEffect(() => {
    loadComments();
  }, [loadComments]);

  const submitGuestComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!screenId || !commentBody.trim() || sendingComment) return;
    setSendingComment(true);
    setCommentError(null);
    try {
      const pwdQuery = password ? `?password=${encodeURIComponent(password)}` : '';
      const res = await fetch(`/api/public/p/${slug}/comments${pwdQuery}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          screen_id: screenId,
          body: commentBody.trim(),
          guest_name: guestName.trim() || undefined,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Não foi possível enviar o comentário');
      }
      const created = await res.json();
      setComments(prev => [...prev, created]);
      setCommentBody('');
    } catch (err: any) {
      setCommentError(err.message);
    } finally {
      setSendingComment(false);
    }
  };

  // Sincroniza cenário ativo com o iframe em tempo real
  useEffect(() => {
    const activeScenario = projectData?.scenarios?.[currentScenarioIndex];
    if (activeScenario && iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({
        type: 'MOCKBIRD_APPLY_SCENARIO',
        data: activeScenario.data || {},
      }, '*');
    }
  }, [currentScenarioIndex, projectData?.scenarios]);

  // Gera HTML e Mock Runtime isolado declarativamente para renderizar via srcDoc
  const htmlDoc = useMemo(() => {
    if (!activeScreen) return '';
    const cssVars = Object.entries(resolvedTokens)
      .map(([k, v]) => `--${k}: ${v};`)
      .join('\n');

    const activeScenario = projectData?.scenarios?.[currentScenarioIndex];
    const scenarioJsonStr = JSON.stringify(activeScenario?.data || {});

    const runtimeJs = `
      var initialData = ${scenarioJsonStr};

      function post(payload) {
        window.parent.postMessage(payload, '*');
      }

      function getNestedValue(obj, path) {
        if (!obj || !path) return undefined;
        var parts = path.split('.');
        var cur = obj;
        for (var i = 0; i < parts.length; i++) {
          if (cur == null) return undefined;
          cur = cur[parts[i]];
        }
        return cur;
      }

      function evaluateCondition(obj, cond) {
        if (!cond) return true;
        if (cond.indexOf('!=') >= 0) {
          var p = cond.split('!=');
          return String(getNestedValue(obj, p[0].trim())) !== p[1].trim();
        }
        if (cond.indexOf('=') >= 0) {
          var p = cond.split('=');
          return String(getNestedValue(obj, p[0].trim())) === p[1].trim();
        }
        var val = getNestedValue(obj, cond.trim());
        return !!val;
      }

      function applyMockData(data) {
        if (!data || typeof data !== 'object') return;
        window.__MOCK_DATA__ = data;
        document.querySelectorAll('[data-mock]').forEach(function(el) {
          var path = el.getAttribute('data-mock');
          if (!path) return;
          var val = getNestedValue(data, path);
          if (val !== undefined && val !== null) {
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') el.value = String(val);
            else el.innerText = String(val);
          }
        });
        document.querySelectorAll('[data-mock-show]').forEach(function(el) {
          var cond = el.getAttribute('data-mock-show');
          el.style.display = evaluateCondition(data, cond) ? '' : 'none';
        });
        document.querySelectorAll('[data-mock-hide]').forEach(function(el) {
          var cond = el.getAttribute('data-mock-hide');
          el.style.display = evaluateCondition(data, cond) ? 'none' : '';
        });
        document.querySelectorAll('[data-mock-list]').forEach(function(container) {
          var listKey = container.getAttribute('data-mock-list');
          var items = getNestedValue(data, listKey);
          if (!Array.isArray(items)) return;
          if (!container._mockTemplate) {
            var firstChild = container.firstElementChild;
            if (!firstChild) return;
            container._mockTemplate = firstChild.cloneNode(true);
          }
          container.innerHTML = '';
          if (items.length === 0) return;
          items.forEach(function(item) {
            var clone = container._mockTemplate.cloneNode(true);
            if (typeof item === 'object' && item !== null) {
              clone.querySelectorAll('[data-mock-item]').forEach(function(itemEl) {
                var prop = itemEl.getAttribute('data-mock-item');
                var val = item[prop];
                if (val !== undefined && val !== null) itemEl.innerText = String(val);
              });
            } else {
              clone.innerText = String(item);
            }
            container.appendChild(clone);
          });
        });
      }

      function mockTarget(node) {
        if (!node || !node.closest) return null;
        const goEl = node.closest('[data-go]');
        if (goEl) {
          const value = (goEl.getAttribute('data-go') || '').trim();
          if (value && value !== '#') return { kind: 'screen', target: value };
        }
        const link = node.closest('a[href]');
        if (!link || link.hasAttribute('download')) return null;
        const href = (link.getAttribute('href') || '').trim();
        if (!href || href === '#' || href.indexOf('javascript:') === 0) return null;
        if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.indexOf('//') === 0) {
          return { kind: 'external', target: href };
        }
        return { kind: 'screen', target: href };
      }

      document.addEventListener('click', (e) => {
        // Toast
        const toastEl = e.target.closest('[data-toast]');
        if (toastEl) {
          const msg = toastEl.getAttribute('data-toast');
          if (msg) post({ type: 'MOCK_TOAST', message: msg });
        }

        // Modal Overlay: abrir
        const overlayBtn = e.target.closest('[data-overlay]');
        if (overlayBtn) {
          const id = overlayBtn.getAttribute('data-overlay');
          if (id) {
            const targetModal = document.getElementById(id) ||
              document.querySelector('[data-mb-id=\"' + id + '\"]') ||
              document.querySelector('[data-mb-id*=\"' + id + '\"]');
            if (targetModal) {
              e.preventDefault();
              targetModal.style.display = 'flex';
              targetModal.classList.remove('hidden');
              return;
            }
          }
        }

        // Modal Overlay: fechar
        const closeBtn = e.target.closest('[data-close]');
        if (closeBtn) {
          const modal = closeBtn.closest('[data-mb-id*=\"modal\"], [data-mb-id*=\"overlay\"], [role=\"dialog\"], .fixed');
          if (modal) {
            e.preventDefault();
            modal.style.display = 'none';
            return;
          }
        }

        // Navegação entre telas
        const nav = mockTarget(e.target);
        if (nav) {
          e.preventDefault();
          if (nav.kind === 'screen') {
            post({ type: 'MOCKBIRD_NAVIGATE', target: nav.target });
          } else if (nav.target) {
            window.open(nav.target, '_blank');
          }
        }
      });

      // Envio de formulário navega para tela destino
      document.addEventListener('submit', (e) => {
        e.preventDefault();
        const form = e.target;
        if (!form || !form.getAttribute) return;
        const go = (form.getAttribute('data-go') || form.getAttribute('action') || '').trim();
        if (go && go !== '#' && go.indexOf('javascript:') !== 0) {
          post({ type: 'MOCKBIRD_NAVIGATE', target: go });
        }
      });

      window.addEventListener('message', function(ev) {
        if (!ev.data) return;
        if (ev.data.type === 'MOCKBIRD_APPLY_SCENARIO') {
          applyMockData(ev.data.data);
          return;
        }
        if (ev.data.type === 'MOCKBIRD_SET_THEME') {
          var theme = ev.data.theme || 'dark';
          document.documentElement.setAttribute('data-theme', theme);
          document.documentElement.style.colorScheme = theme;
          if (theme === 'dark') {
            document.documentElement.classList.add('dark');
            if (document.body) document.body.classList.add('dark');
          } else {
            document.documentElement.classList.remove('dark');
            if (document.body) document.body.classList.remove('dark');
          }
          if (ev.data.tokens) {
            var themeTokens = ev.data.tokens;
            var dynStyle = document.getElementById('mockbird-dynamic-tokens');
            if (!dynStyle) {
              dynStyle = document.createElement('style');
              dynStyle.id = 'mockbird-dynamic-tokens';
              document.head.appendChild(dynStyle);
            }
            var cssRules = Object.keys(themeTokens).map(function(k) {
              return '--' + k + ': ' + themeTokens[k] + ';';
            }).join('\n');
            dynStyle.textContent = ':root, [data-theme="' + theme + '"], html, body { ' + cssRules + ' }';
          }
          return;
        }
      });

      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { applyMockData(initialData); });
      } else {
        applyMockData(initialData);
      }
    `;

    const injectedStyles = `
      <style id=\"mockbird-presentation-styles\">
        :root {
          ${cssVars}
        }
        html {
          width: 100%;
          min-height: 100%;
          color-scheme: ${presentationTheme};
        }
        body {
          margin: 0;
          padding: 0;
          width: 100%;
          min-height: 100%;
          background-color: var(--color-bg, ${presentationTheme === 'light' ? '#ffffff' : '#09090b'});
          color: var(--color-text, ${presentationTheme === 'light' ? '#0f172a' : '#f8fafc'});
        }
        a[href], [data-go], [data-overlay], [data-close] {
          cursor: pointer;
        }
      </style>
    `;

    const fullRuntimeScript = `<script id=\"mockbird-presentation-runtime\">${runtimeJs}</script>`;
    const raw = applyThemeToHtml((activeScreen.html_content || '').trim(), presentationTheme);
    const hasTailwind = raw.includes('cdn.tailwindcss.com');
    const tailwindTag = hasTailwind ? '' : '<script id=\"mockbird-tailwind-config\">window.tailwind = { config: { darkMode: \"class\" } };</script><script id=\"mockbird-tailwind-script\" src=\"https://cdn.tailwindcss.com\"></script>';

    if (raw.toLowerCase().includes('<!doctype') || raw.toLowerCase().includes('<html')) {
      let doc = raw;
      if (doc.includes('</head>')) {
        doc = doc.replace('</head>', `${tailwindTag}${injectedStyles}${fullRuntimeScript}</head>`);
      } else {
        doc = `${tailwindTag}${injectedStyles}${fullRuntimeScript}${doc}`;
      }
      return doc;
    }

    return `
      <!doctype html>
      <html lang=\"pt-BR\" data-theme=\"${presentationTheme}\" class=\"${presentationTheme === 'dark' ? 'dark' : ''}\" style=\"color-scheme: ${presentationTheme};\">
        <head>
          <meta charset=\"utf-8\" />
          <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
          ${tailwindTag}
          ${injectedStyles}
        </head>
        <body>
          <div id=\"mockbird-root\" style=\"width: 100%; min-height: 100vh;\">
            ${raw}
          </div>
          ${fullRuntimeScript}
        </body>
      </html>
    `;
  }, [activeScreen, resolvedTokens]);

  if (needsPassword) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex items-center justify-center p-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            loadPresentation(password);
          }}
          className="w-full max-w-sm bg-mockbird-surface border border-mockbird-border rounded-2xl p-6 space-y-4"
        >
          <div className="flex items-center gap-2 text-white font-semibold">
            <Lock size={16} className="text-mockbird-cyan" /> Apresentação protegida
          </div>
          <p className="text-xs text-slate-400">Informe a senha recebida para abrir este protótipo.</p>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Senha de acesso"
            className="w-full px-3 py-2 rounded-lg bg-mockbird-bg border border-mockbird-border text-sm text-white focus:outline-none focus:border-mockbird-cyan"
          />
          {passwordError && <p className="text-xs text-rose-400">{passwordError}</p>}
          <button type="submit" className="w-full bg-mockbird-blue hover:bg-mockbird-bluedark text-white text-xs font-semibold py-2 rounded-lg">
            Abrir apresentação
          </button>
        </form>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-slate-400">
          <div className="w-4 h-4 border-2 border-mockbird-blue border-t-transparent rounded-full animate-spin"></div>
          <span>Carregando protótipo para apresentação...</span>
        </div>
      </div>
    );
  }

  if (error || !projectData) {
    return (
      <div className="min-h-screen bg-[#09090b] text-slate-100 flex flex-col items-center justify-center p-6 text-center">
        <h1 className="text-xl font-bold text-white mb-2">Protótipo não encontrado</h1>
        <p className="text-sm text-slate-400 max-w-md mb-6">{error || 'O link pode estar expirado ou o slug foi alterado.'}</p>
        {onBackToApp && (
          <button
            onClick={onBackToApp}
            className="bg-mockbird-blue text-white text-xs font-semibold px-4 py-2 rounded-lg"
          >
            Voltar ao Painel
          </button>
        )}
      </div>
    );
  }

  const screens = projectData.screens || [];

  return (
    <div className="h-screen w-screen bg-[#09090b] flex flex-col overflow-hidden select-none">
      
      {/* Toast flutuante de interação */}
      {toastMessage && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 bg-mockbird-blue hover:bg-mockbird-bluedark text-white px-5 py-2.5 rounded-xl shadow-panel flex items-center gap-2.5 text-xs font-semibold animate-in slide-in-from-top-4">
          <Bell size={15} className="text-mockbird-cyan animate-pulse" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Barra de Controle Executiva e Minimalista */}
      <div className="h-10 bg-[#09090b]/80 border-b border-white/10 px-4 flex items-center justify-between gap-4 z-40 backdrop-blur-md shrink-0">
        <div className="flex items-center gap-3">
          {onBackToApp && (
            <button
              onClick={onBackToApp}
              className="p-1 rounded text-slate-400 hover:text-white hover:bg-white/5 transition flex items-center gap-1.5 text-xs"
              title="Voltar ao Editor"
            >
              <ArrowLeft size={14} />
              <span className="hidden sm:inline text-[11px]">Editor</span>
            </button>
          )}

          <span className="font-semibold text-xs text-slate-200 tracking-tight">
            {projectData.project_name || projectData.name}
          </span>
        </div>

        {/* Controles Centrais: Barra de Dispositivos e Responsividade Fiel ao Chrome DevTools + Seletor de Tela */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-[#1b2228] border border-[#2d3a42] rounded-lg px-2.5 py-1 text-xs shadow-inner">
            <MoreVertical size={13} className="text-slate-400 shrink-0" />
            
            <span className="text-[11px] font-medium text-slate-300">Dimensions:</span>
            
            <select
              value={deviceKey}
              onChange={(e) => handleDeviceSelect(e.target.value)}
              className="bg-[#12171b] border border-[#303d46] text-slate-200 px-2 py-0.5 rounded text-[11px] font-medium focus:outline-none focus:border-[#58a6ff] cursor-pointer"
            >
              <option value="responsive" className="bg-[#1b2228]">Responsive</option>
              <option value="iphone16" className="bg-[#1b2228]">iPhone 16</option>
              <option value="iphone14pro" className="bg-[#1b2228]">iPhone 14 Pro</option>
              <option value="pixel7" className="bg-[#1b2228]">Pixel 7</option>
              <option value="ipad_air" className="bg-[#1b2228]">iPad Air</option>
              <option value="desktop" className="bg-[#1b2228]">Desktop HD (1440 × 900)</option>
              <option value="laptop" className="bg-[#1b2228]">Laptop (1366 × 768)</option>
            </select>

            {deviceKey !== 'responsive' && (
              <div className="flex items-center gap-1 font-mono text-[11px]">
                <input
                  type="number"
                  min="1"
                  value={activeWidth}
                  onChange={(e) => {
                    const val = Math.max(1, Number(e.target.value) || 1);
                    if (isLandscape) setDeviceHeight(val);
                    else setDeviceWidth(val);
                  }}
                  className="w-14 bg-[#12171b] border border-[#303d46] text-slate-200 px-1 py-0.5 rounded text-center focus:outline-none focus:border-[#58a6ff]"
                />
                <span className="text-slate-500">×</span>
                <input
                  type="number"
                  min="1"
                  value={activeHeight}
                  onChange={(e) => {
                    const val = Math.max(1, Number(e.target.value) || 1);
                    if (isLandscape) setDeviceWidth(val);
                    else setDeviceHeight(val);
                  }}
                  className="w-14 bg-[#12171b] border border-[#303d46] text-slate-200 px-1 py-0.5 rounded text-center focus:outline-none focus:border-[#58a6ff]"
                />
              </div>
            )}

            <select
              value={zoomScale}
              onChange={(e) => setZoomScale(e.target.value === 'fit' ? 'fit' : Number(e.target.value))}
              className="bg-[#12171b] border border-[#303d46] text-slate-200 px-1.5 py-0.5 rounded text-[11px] focus:outline-none focus:border-[#58a6ff] cursor-pointer"
            >
              <option value="fit" className="bg-[#1b2228]">Fit to window</option>
              <option value={0.5} className="bg-[#1b2228]">50%</option>
              <option value={0.75} className="bg-[#1b2228]">75%</option>
              <option value={1} className="bg-[#1b2228]">100%</option>
              <option value={1.25} className="bg-[#1b2228]">125%</option>
              <option value={1.5} className="bg-[#1b2228]">150%</option>
            </select>

            <select
              value={throttle}
              onChange={(e) => setThrottle(e.target.value as any)}
              className="bg-[#12171b] border border-[#303d46] text-slate-200 px-1.5 py-0.5 rounded text-[11px] focus:outline-none focus:border-[#58a6ff] cursor-pointer hidden md:inline"
            >
              <option value="off" className="bg-[#1b2228]">No throttling</option>
              <option value="slow3g" className="bg-[#1b2228]">Slow 3G</option>
              <option value="4g" className="bg-[#1b2228]">4G</option>
            </select>

            <span className="text-[11px] text-slate-400 hidden xl:inline">
              'Save-Data': default
            </span>

            <button
              type="button"
              onClick={() => setIsLandscape((prev) => !prev)}
              className="p-1 rounded bg-[#12171b] border border-[#303d46] text-slate-300 hover:text-white transition"
              title="Alternar orientação (Retrato / Paisagem)"
            >
              <RotateCw size={13} className={isLandscape ? 'rotate-90 transition-transform' : 'transition-transform'} />
            </button>
          </div>

          {/* Seletor Discreto de Tela */}
          {screens.length > 1 ? (
            <div className="relative flex items-center">
              <select
                value={currentScreenIndex}
                onChange={(e) => setCurrentScreenIndex(Number(e.target.value))}
                className="bg-white/5 border border-white/10 text-slate-300 hover:text-white px-2.5 py-1 rounded-md text-xs font-medium focus:outline-none cursor-pointer appearance-none pr-6 transition"
                title="Alternar tela"
                aria-label="Tela"
              >
                {screens.map((s: any, idx: number) => (
                  <option key={s.id || idx} value={idx} className="bg-slate-900 text-white">
                    {s.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={12} className="text-slate-400 absolute right-2 pointer-events-none" />
            </div>
          ) : (
            <span className="text-[11px] text-slate-500 font-mono hidden lg:inline">
              {activeScreen?.name || 'Tela Principal'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Alternar Tema Light / Dark */}
          <button
            onClick={() => setPresentationTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))}
            className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-white/5 transition"
            title={presentationTheme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
            aria-label="Alternar tema"
          >
            {presentationTheme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>

          {/* Menu Discreto de Opções da Apresentação */}
          {(projectData?.scenarios?.length > 0 || screens.length > 1) && (
            <div className="relative">
              <button
                onClick={() => setShowSettingsMenu((v) => !v)}
                className={`p-1.5 rounded-md transition ${showSettingsMenu ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white hover:bg-white/5'}`}
                title="Opções de visualização"
                aria-label="Opções"
              >
                <Settings2 size={14} />
              </button>

              {showSettingsMenu && (
                <div className="absolute right-0 top-full mt-2 w-56 rounded-xl bg-mockbird-surface border border-mockbird-border p-2.5 shadow-2xl z-50 text-xs space-y-2.5 animate-in fade-in slide-in-from-top-1">
                  {projectData?.scenarios?.length > 0 && (
                    <div className="space-y-1">
                      <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Cenário de Dados</span>
                      <select
                        value={currentScenarioIndex}
                        onChange={(e) => {
                          setCurrentScenarioIndex(Number(e.target.value));
                          setShowSettingsMenu(false);
                        }}
                        className="w-full px-2 py-1.5 rounded-lg bg-mockbird-card border border-mockbird-border text-slate-200 text-xs focus:outline-none"
                      >
                        {projectData.scenarios.map((sc: any, idx: number) => (
                          <option key={sc.id || idx} value={idx}>
                            {sc.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <button
                    onClick={() => {
                      const mainIdx = screens.findIndex((s: any) => s.is_main);
                      setCurrentScreenIndex(mainIdx >= 0 ? mainIdx : 0);
                      setShowSettingsMenu(false);
                    }}
                    className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-mockbird-card text-slate-300 hover:text-white transition text-left"
                  >
                    <RotateCcw size={13} />
                    <span>Reiniciar Fluxo</span>
                  </button>
                </div>
              )}
            </div>
          )}

          {commentsEnabled && (
            <button
              onClick={() => setCommentsOpen((v) => !v)}
              className="px-2 py-1 rounded-md text-xs font-medium text-slate-400 hover:text-white hover:bg-white/5 transition flex items-center gap-1.5"
              title="Comentários nesta tela"
            >
              <MessageSquare size={14} />
              <span>{comments.length > 0 ? `(${comments.length})` : 'Comentar'}</span>
            </button>
          )}

          {/* Fullscreen */}
          <button
            onClick={toggleFullscreen}
            className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-white/5 transition"
            title={isFullscreen ? 'Sair da tela cheia' : 'Tela cheia'}
            aria-label="Tela cheia"
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* Frame de Apresentação com Suporte a Responsividade e Device Frames */}
      <div 
        ref={viewportContainerRef}
        className={`flex-1 w-full min-h-0 relative ${
          deviceKey === 'responsive' 
            ? 'bg-[#09090b] overflow-hidden' 
            : 'bg-[#0c0d10] bg-[radial-gradient(#ffffff08_1px,transparent_1px)] [background-size:24px_24px] overflow-auto flex items-center justify-center p-6'
        }`}
      >
        {deviceKey === 'responsive' ? (
          <iframe
            ref={iframeRef}
            title={activeScreen?.name || 'Apresentação'}
            srcDoc={htmlDoc}
            sandbox="allow-scripts allow-forms allow-modals"
            className="absolute inset-0 w-full h-full border-0 block"
          />
        ) : (
          <div
            className="transition-all duration-200 ease-out origin-center flex flex-col items-center justify-center"
            style={{
              transform: `scale(${currentScale})`,
            }}
          >
            {/* Viewport Limpo (sem carcaça de telefone, tablet ou navegador) */}
            <div 
              className="relative rounded-lg overflow-hidden bg-black shadow-[0_25px_70px_rgba(0,0,0,0.85)] border border-white/10 transition-all duration-200"
              style={{
                width: `${activeWidth}px`,
                height: `${activeHeight}px`,
              }}
            >
              <iframe
                ref={iframeRef}
                title={activeScreen?.name || 'Apresentação'}
                srcDoc={htmlDoc}
                sandbox="allow-scripts allow-forms allow-modals"
                className="w-full h-full border-0 block"
              />
            </div>

            {/* Badge discreto com informações do dispositivo */}
            <div className="mt-3 px-3 py-1 rounded-full bg-black/60 border border-white/10 backdrop-blur-md text-[11px] text-slate-400 font-mono flex items-center gap-2">
              <span>{PRESENTATION_DEVICES[deviceKey]?.name || 'Custom'} ({activeWidth} × {activeHeight})</span>
              <span className="text-white/20">•</span>
              <span>{Math.round(currentScale * 100)}% zoom</span>
            </div>
          </div>
        )}
      </div>

      {commentsEnabled && commentsOpen && (
        <aside className="fixed top-12 right-0 bottom-0 w-80 bg-mockbird-surface border-l border-mockbird-border flex flex-col z-40 shadow-2xl">
          <div className="h-11 px-4 flex items-center justify-between border-b border-mockbird-border shrink-0">
            <span className="text-xs font-semibold text-white flex items-center gap-1.5">
              <MessageSquare size={14} className="text-mockbird-cyan" /> Comentários da tela
            </span>
            <button onClick={() => setCommentsOpen(false)} className="text-slate-400 hover:text-white" aria-label="Fechar comentários">
              <X size={15} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
            {comments.length === 0 && (
              <p className="text-[11px] text-slate-500 text-center py-8">Seja o primeiro a comentar esta tela.</p>
            )}
            {comments.map(c => (
              <div key={c.id} className="p-2.5 rounded-lg bg-mockbird-card border border-mockbird-border text-xs space-y-1">
                <div className="flex items-center justify-between text-[10px] text-slate-400">
                  <span className="font-semibold text-slate-200">{c.author_name}</span>
                  <span className="font-mono">{new Date(c.created_at).toLocaleDateString('pt-BR')}</span>
                </div>
                <p className="text-slate-300 leading-relaxed">{c.body}</p>
              </div>
            ))}
          </div>

          <form onSubmit={submitGuestComment} className="p-3 border-t border-mockbird-border space-y-2 shrink-0">
            <input
              type="text"
              value={guestName}
              onChange={(e) => setGuestName(e.target.value)}
              placeholder="Seu nome (opcional)"
              maxLength={80}
              className="w-full px-2.5 py-1.5 rounded-md bg-mockbird-bg border border-mockbird-border text-xs text-white focus:outline-none focus:border-mockbird-cyan"
            />
            <textarea
              rows={3}
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="Deixe um comentário sobre esta tela…"
              maxLength={4000}
              className="w-full px-2.5 py-1.5 rounded-md bg-mockbird-bg border border-mockbird-border text-xs text-white focus:outline-none focus:border-mockbird-cyan resize-none"
            />
            {commentError && <p className="text-[11px] text-rose-400">{commentError}</p>}
            <button
              type="submit"
              disabled={sendingComment || !commentBody.trim()}
              className="w-full bg-mockbird-blue hover:bg-mockbird-bluedark disabled:opacity-50 text-white text-xs font-semibold py-2 rounded-md flex items-center justify-center gap-1.5"
            >
              <Send size={12} /> {sendingComment ? 'Enviando…' : 'Enviar comentário'}
            </button>
          </form>
        </aside>
      )}
    </div>
  );
};
