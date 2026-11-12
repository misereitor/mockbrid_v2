/**
 * Bundle de design (`mockbird.design-bundle/v1`).
 *
 * O editor renderiza cada tela num iframe oculto, extrai as camadas visíveis
 * (retângulos, textos e imagens em coordenadas absolutas) e gera um JSON que os
 * plugins do Figma/Penpot e a extensão de navegador consomem. O formato está
 * documentado em `docs/design-bundle.md`.
 */

import { buildCanvasDoc } from './canvasDoc';

export interface BundleLayer {
  type: 'rect' | 'text' | 'image';
  name?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Cor de preenchimento em hex (`#rrggbb`). */
  fill?: string;
  fillOpacity?: number;
  radius?: number;
  border?: { color: string; width: number };
  color?: string;
  fontSize?: number;
  fontWeight?: number;
  fontFamily?: string;
  /** Altura de linha em px (0 = automática). */
  lineHeight?: number;
  letterSpacing?: number;
  align?: 'left' | 'center' | 'right' | 'justify';
  text?: string;
  /** URL ou data URI da imagem. */
  src?: string;
  opacity?: number;
}

export interface BundleScreen {
  id: string;
  name: string;
  width: number;
  height: number;
  device_type?: string;
  is_entry?: boolean;
  background: string;
  html: string;
  css?: string;
  layers: BundleLayer[];
}

export interface BundleTokens {
  light: Record<string, string>;
  dark: Record<string, string>;
  shared?: Record<string, string>;
}

export interface DesignBundle {
  format: 'mockbird.design-bundle';
  version: 1;
  exported_at: string;
  project: { id: string; name: string; slug?: string };
  tokens: BundleTokens;
  screens: BundleScreen[];
  warnings?: string[];
}

export interface ScreenLike {
  id: string;
  name: string;
  html_content: string;
  css_content?: string;
  width?: number;
  height?: number;
  device_type?: string;
  is_entry?: boolean;
}

export interface RenderedScreen {
  layers: BundleLayer[];
  background: string;
}

/** Limite de telas por bundle para não travar o navegador. */
export const MAX_BUNDLE_SCREENS = 60;

const SKIP_TAGS = new Set([
  'SCRIPT',
  'STYLE',
  'LINK',
  'META',
  'NOSCRIPT',
  'TEMPLATE',
  'HEAD',
  'TITLE',
  'BR',
  'OPTION',
]);

const round = (value: number) => Math.round(value * 100) / 100;

function rgbToHex(r: number, g: number, b: number): string {
  const to = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  return `#${to(r)}${to(g)}${to(b)}`;
}

/** Interpreta `rgb()`/`rgba()`/hex do CSS. Devolve `null` quando transparente. */
export function parseCssColor(value: string | undefined | null): { hex: string; alpha: number } | null {
  if (!value) return null;
  const text = value.trim().toLowerCase();
  if (!text || text === 'transparent' || text === 'none' || text === 'currentcolor') return null;

  const fn = text.match(/^rgba?\(([^)]+)\)$/);
  if (fn) {
    const parts = fn[1].split(',').map((part) => parseFloat(part.trim()));
    if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return null;
    const alpha = parts.length > 3 ? parts[3] : 1;
    if (alpha <= 0) return null;
    return { hex: rgbToHex(parts[0], parts[1], parts[2]), alpha };
  }

  const hex = text.match(/^#([0-9a-f]{3,8})$/);
  if (hex) {
    const raw = hex[1];
    if (raw.length === 3) {
      return { hex: `#${raw[0]}${raw[0]}${raw[1]}${raw[1]}${raw[2]}${raw[2]}`, alpha: 1 };
    }
    if (raw.length === 6) return { hex: `#${raw}`, alpha: 1 };
    if (raw.length === 8) {
      const alpha = parseInt(raw.slice(6, 8), 16) / 255;
      if (alpha <= 0) return null;
      return { hex: `#${raw.slice(0, 6)}`, alpha: round(alpha) };
    }
  }

  return null;
}

function firstGradientColor(backgroundImage: string | undefined): { hex: string; alpha: number } | null {
  if (!backgroundImage || !backgroundImage.includes('gradient')) return null;
  const matches = backgroundImage.match(/rgba?\([^)]+\)|#[0-9a-f]{3,8}/gi) || [];
  for (const match of matches) {
    const parsed = parseCssColor(match);
    if (parsed) return parsed;
  }
  return null;
}

function px(value: string | undefined): number {
  const parsed = parseFloat(value || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

function describeElement(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const id = el.getAttribute('id');
  if (id) return `${tag}#${id}`;
  const classes = (el.getAttribute('class') || '')
    .split(/\s+/)
    .filter((name) => name && !name.startsWith('mb-'))
    .slice(0, 2);
  return classes.length ? `${tag}.${classes.join('.')}` : tag;
}

function firstFontFamily(value: string): string {
  const first = (value || '').split(',')[0] || 'Inter';
  const cleaned = first.replace(/["']/g, '').trim();
  return cleaned || 'Inter';
}

function alignmentOf(value: string): 'left' | 'center' | 'right' | 'justify' {
  if (value === 'center' || value === 'right' || value === 'justify') return value;
  return 'left';
}

/**
 * Percorre o DOM renderizado e devolve as camadas em coordenadas absolutas.
 * Textos são extraídos por nó de texto (a caixa vem do `Range`), assim
 * elementos com trechos em `strong`/`a` não duplicam conteúdo.
 */
export function extractLayers(doc: Document, width: number, height: number): BundleLayer[] {
  const view = doc.defaultView;
  if (!view) return [];

  const layers: BundleLayer[] = [];
  const add = (layer: BundleLayer) => {
    if (!Number.isFinite(layer.x) || !Number.isFinite(layer.y)) return;
    if (layer.width < 1 || layer.height < 1) return;
    layers.push({
      ...layer,
      x: round(layer.x),
      y: round(layer.y),
      width: round(layer.width),
      height: round(layer.height),
    });
  };

  const visit = (el: Element, depth: number) => {
    if (depth > 40) return;
    const tag = el.tagName.toUpperCase();
    if (SKIP_TAGS.has(tag)) return;

    const style = view.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const opacity = parseFloat(style.opacity);
    if (Number.isFinite(opacity) && opacity === 0) return;

    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) {
      // Elementos sem caixa ainda podem ter filhos posicionados.
      Array.from(el.children).forEach((child) => visit(child, depth + 1));
      return;
    }

    const name = describeElement(el);

    if (tag === 'SVG') {
      try {
        const markup = new XMLSerializer().serializeToString(el);
        add({
          type: 'image',
          name,
          x: rect.left,
          y: rect.top,
          width: rect.width,
          height: rect.height,
          src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`,
          opacity: opacity < 1 ? round(opacity) : undefined,
        });
      } catch {
        /* svg não serializável: ignora */
      }
      return;
    }

    if (tag === 'IMG') {
      const img = el as HTMLImageElement;
      const src = img.currentSrc || img.getAttribute('src') || '';
      if (src) {
        add({
          type: 'image',
          name,
          x: rect.left,
          y: rect.top,
          width: rect.width,
          height: rect.height,
          src,
          radius: px(style.borderTopLeftRadius) || undefined,
          opacity: opacity < 1 ? round(opacity) : undefined,
        });
      }
      return;
    }

    const solidBackground = parseCssColor(style.backgroundColor);
    const background = solidBackground || firstGradientColor(style.backgroundImage);
    const borderWidth = px(style.borderTopWidth);
    const borderColor = parseCssColor(style.borderTopColor);
    const hasBorder = borderWidth > 0 && !!borderColor && style.borderTopStyle !== 'none';
    const radius = px(style.borderTopLeftRadius);

    // O fundo do body já vira o preenchimento do frame (`screen.background`).
    if ((background || hasBorder) && !(tag === 'BODY' && solidBackground && !hasBorder)) {
      add({
        type: 'rect',
        name,
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        fill: background?.hex,
        fillOpacity: background ? round(background.alpha) : undefined,
        radius: radius || undefined,
        border: hasBorder && borderColor ? { color: borderColor.hex, width: round(borderWidth) } : undefined,
        opacity: opacity < 1 ? round(opacity) : undefined,
      });
    }

    const fontSize = px(style.fontSize);
    const paddingLeft = px(style.paddingLeft);
    const paddingRight = px(style.paddingRight);
    const lineHeight = px(style.lineHeight);
    const color = parseCssColor(style.color);

    if (fontSize > 0) {
      for (const node of Array.from(el.childNodes)) {
        if (node.nodeType !== 3) continue;
        const raw = (node.textContent || '').replace(/\s+/g, ' ').trim();
        if (!raw) continue;

        let box = new DOMRect(rect.left, rect.top, 0, 0);
        try {
          const range = doc.createRange();
          range.selectNodeContents(node);
          box = range.getBoundingClientRect();
        } catch {
          box = new DOMRect(rect.left + paddingLeft, rect.top, rect.width, rect.height);
        }
        if (box.width < 1 || box.height < 1) continue;

        const lineBox = lineHeight > 0 ? lineHeight : fontSize * 1.4;
        const wrapped = box.height > lineBox * 1.8;
        const textWidth = wrapped ? Math.max(1, rect.width - paddingLeft - paddingRight) : box.width;
        const textX = wrapped ? rect.left + paddingLeft : box.left;

        add({
          type: 'text',
          name: `${name} · texto`,
          x: textX,
          y: box.top,
          width: textWidth,
          height: Math.min(box.height, Math.max(lineBox, fontSize)),
          text: raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw,
          color: color?.hex,
          fontSize: round(fontSize),
          fontWeight: Number.parseInt(style.fontWeight, 10) || 400,
          fontFamily: firstFontFamily(style.fontFamily),
          lineHeight: lineHeight > 0 ? round(lineHeight) : 0,
          letterSpacing: style.letterSpacing === 'normal' ? 0 : round(px(style.letterSpacing)),
          align: alignmentOf(style.textAlign),
          opacity: opacity < 1 ? round(opacity) : undefined,
        });
      }
    }

    Array.from(el.children).forEach((child) => visit(child, depth + 1));
  };

  if (doc.body) visit(doc.body, 0);

  // Descarta camadas totalmente fora da tela.
  return layers.filter((layer) => layer.x < width + 400 && layer.y < height + 400);
}

function readBackground(doc: Document): string {
  const view = doc.defaultView;
  if (!view || !doc.body) return '#ffffff';
  const color = parseCssColor(view.getComputedStyle(doc.body).backgroundColor);
  return color?.hex || '#ffffff';
}

/** Marca o documento de exportação para saber quando o `srcdoc` já carregou. */
const EXPORT_MARKER = '<div data-mockbird-export="1" style="display:none"></div>';

function buildScreenDocument(
  screen: { html: string; css?: string },
  tokens: Record<string, string>,
): string {
  const documentHtml = buildCanvasDoc(screen.html || '', tokens);
  const withCss = screen.css
    ? documentHtml.includes('</head>')
      ? documentHtml.replace('</head>', `<style>${screen.css}</style></head>`)
      : `<style>${screen.css}</style>${documentHtml}`
    : documentHtml;

  // Marca dentro do body: um comentário antes do doctype mudaria o modo de renderização.
  const bodyTag = withCss.match(/<body[^>]*>/i);
  if (bodyTag && bodyTag.index !== undefined) {
    const at = bodyTag.index + bodyTag[0].length;
    return `${withCss.slice(0, at)}${EXPORT_MARKER}${withCss.slice(at)}`;
  }
  return `${withCss}${EXPORT_MARKER}`;
}

/**
 * Espera o documento do `srcdoc` ficar pronto.
 *
 * O iframe dispara `load` para o `about:blank` inicial antes de navegar para o
 * `srcdoc`; por isso a espera é pelo marcador do nosso documento.
 */
function waitForFrameDocument(iframe: HTMLIFrameElement, timeoutMs: number): Promise<Document> {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      const doc = iframe.contentDocument;
      if (doc && doc.readyState === 'complete' && doc.body && doc.body.innerHTML.includes('mockbird-export')) {
        resolve(doc);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error('Tempo esgotado ao renderizar a tela para exportação.'));
        return;
      }
      window.setTimeout(tick, 50);
    };
    tick();
  });
}

function waitForLayout(doc: Document): Promise<void> {
  return new Promise((resolve) => {
    const fonts = (doc as unknown as { fonts?: { ready?: Promise<unknown> } }).fonts;
    const afterFonts = () => {
      requestAnimationFrame(() => requestAnimationFrame(() => window.setTimeout(resolve, 250)));
    };
    if (fonts?.ready) {
      fonts.ready.then(afterFonts).catch(afterFonts);
    } else {
      afterFonts();
    }
  });
}

/**
 * Renderiza a tela num iframe oculto e extrai as camadas.
 * O iframe fica no mesmo documento do app (o HTML da tela é do próprio usuário).
 */
export async function renderScreenLayers(
  screen: { html: string; css?: string; width: number; height: number },
  tokens: Record<string, string>,
  timeoutMs = 20_000,
): Promise<RenderedScreen> {
  if (typeof document === 'undefined') {
    throw new Error('A extração de camadas precisa rodar no navegador.');
  }

  const iframe = document.createElement('iframe');
  iframe.setAttribute('aria-hidden', 'true');
  iframe.setAttribute('tabindex', '-1');
  iframe.style.cssText = `position:fixed;left:-20000px;top:0;width:${screen.width}px;height:${screen.height}px;border:0;background:#ffffff;`;
  // `srcdoc` antes de entrar no DOM evita a navegação inicial para `about:blank`.
  iframe.srcdoc = buildScreenDocument(screen, tokens);

  document.body.appendChild(iframe);

  try {
    const frameDoc = await waitForFrameDocument(iframe, timeoutMs);
    await waitForLayout(frameDoc);
    return {
      layers: extractLayers(frameDoc, screen.width, screen.height),
      background: readBackground(frameDoc),
    };
  } finally {
    iframe.remove();
  }
}

function renderTokenMap(tokens: BundleTokens): Record<string, string> {
  const merged: Record<string, string> = {};
  const put = (source?: Record<string, string | unknown>) => {
    Object.entries(source || {}).forEach(([key, value]) => {
      if (typeof value === 'string') merged[key] = value;
    });
  };
  put(tokens.shared);
  put(tokens.light);
  // O canvas do editor abre no tema escuro por padrão.
  put(tokens.dark);
  return merged;
}

export interface BuildBundleInput {
  project: { id: string; name: string; slug?: string };
  screens: ScreenLike[];
  tokens: BundleTokens;
  onProgress?: (done: number, total: number) => void;
}

/** Gera o bundle completo do projeto (renderizando cada tela). */
export async function buildDesignBundle(input: BuildBundleInput): Promise<DesignBundle> {
  const total = Math.min(input.screens.length, MAX_BUNDLE_SCREENS);
  const renderTokens = renderTokenMap(input.tokens);
  const screens: BundleScreen[] = [];
  const warnings: string[] = [];

  if (input.screens.length > MAX_BUNDLE_SCREENS) {
    warnings.push(
      `O projeto tem ${input.screens.length} telas; apenas as ${MAX_BUNDLE_SCREENS} primeiras foram exportadas.`,
    );
  }

  for (let index = 0; index < total; index += 1) {
    const screen = input.screens[index];
    const width = Math.max(1, Math.round(Number(screen.width) || 1440));
    const height = Math.max(1, Math.round(Number(screen.height) || 900));
    let rendered: RenderedScreen = { layers: [], background: '#ffffff' };

    try {
      rendered = await renderScreenLayers(
        { html: screen.html_content, css: screen.css_content, width, height },
        renderTokens,
      );
    } catch (error) {
      warnings.push(
        `Tela "${screen.name}" exportada sem camadas: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    screens.push({
      id: screen.id,
      name: screen.name,
      width,
      height,
      device_type: screen.device_type,
      is_entry: screen.is_entry,
      background: rendered.background,
      html: screen.html_content || '',
      css: screen.css_content || '',
      layers: rendered.layers,
    });

    input.onProgress?.(index + 1, total);
  }

  return {
    format: 'mockbird.design-bundle',
    version: 1,
    exported_at: new Date().toISOString(),
    project: input.project,
    tokens: {
      light: input.tokens.light || {},
      dark: input.tokens.dark || {},
      shared: input.tokens.shared || {},
    },
    screens,
    ...(warnings.length ? { warnings } : {}),
  };
}

function slugify(value: string): string {
  return (
    value
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'projeto'
  );
}

export function designBundleFilename(project: { name: string; slug?: string }): string {
  return `${slugify(project.slug || project.name)}.mockbird.json`;
}

/** Baixa o bundle como arquivo `.mockbird.json`. */
export function downloadDesignBundle(bundle: DesignBundle, filename: string): void {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}
