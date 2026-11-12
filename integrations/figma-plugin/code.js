/**
 * Plugin do Figma que reconstrói um bundle exportado pelo Mockbird
 * (`mockbird.design-bundle/v1`) como frames com camadas editáveis.
 *
 * Cada tela vira um frame do tamanho real; retângulos, textos e imagens são
 * posicionados em coordenadas absolutas dentro dele. O formato do bundle está
 * em `docs/design-bundle.md`.
 */

figma.showUI(__html__, { width: 460, height: 600, themeColors: true });

const STYLE_BY_WEIGHT = {
  100: 'Thin',
  200: 'Extra Light',
  300: 'Light',
  400: 'Regular',
  500: 'Medium',
  600: 'Semi Bold',
  700: 'Bold',
  800: 'Extra Bold',
  900: 'Black',
};

const GAP_BETWEEN_FRAMES = 120;
const imageCache = new Map();

figma.ui.onmessage = async (message) => {
  if (!message || message.type !== 'import') return;
  try {
    const bundle = JSON.parse(message.json);
    const result = await importBundle(bundle, (done, total) => {
      figma.ui.postMessage({ type: 'progress', done, total });
    });
    figma.ui.postMessage({
      type: 'done',
      screens: result.screens,
      layers: result.layers,
      skipped: result.skipped,
      warnings: result.warnings,
    });
    figma.notify(`Mockbird: ${result.screens} tela(s) e ${result.layers} camada(s) importadas.`);
    if (result.nodes.length) figma.viewport.scrollAndZoomIntoView(result.nodes);
  } catch (error) {
    figma.ui.postMessage({ type: 'error', message: String((error && error.message) || error) });
  }
};

async function importBundle(bundle, onProgress) {
  if (!bundle || bundle.format !== 'mockbird.design-bundle') {
    throw new Error('Arquivo inválido: esperado um bundle do Mockbird (format "mockbird.design-bundle").');
  }
  const screens = Array.isArray(bundle.screens) ? bundle.screens : [];
  if (!screens.length) throw new Error('O bundle não contém telas.');

  let offsetX = 0;
  let layers = 0;
  let skipped = 0;
  const warnings = [];
  const nodes = [];

  for (let index = 0; index < screens.length; index += 1) {
    const screen = screens[index];
    const width = Math.max(1, Math.round(Number(screen.width) || 1440));
    const height = Math.max(1, Math.round(Number(screen.height) || 900));

    const frame = figma.createFrame();
    frame.name = String(screen.name || `Tela ${index + 1}`);
    frame.resize(width, height);
    frame.x = offsetX;
    frame.y = 0;
    frame.clipsContent = true;
    const background = parseCssColor(screen.background);
    frame.fills = background ? [solidFill(background)] : [];
    offsetX += width + GAP_BETWEEN_FRAMES;

    for (const layer of Array.isArray(screen.layers) ? screen.layers : []) {
      try {
        await createLayer(frame, layer);
        layers += 1;
      } catch (error) {
        skipped += 1;
        if (warnings.length < 8) {
          warnings.push(`${screen.name || 'tela'} → ${String((error && error.message) || error)}`);
        }
      }
    }

    nodes.push(frame);
    onProgress(index + 1, screens.length);
  }

  return { screens: screens.length, layers, skipped, warnings, nodes };
}

async function createLayer(parent, layer) {
  const x = Number(layer.x) || 0;
  const y = Number(layer.y) || 0;
  const width = Math.max(1, Number(layer.width) || 1);
  const height = Math.max(1, Number(layer.height) || 1);
  const radius = Number(layer.radius) || 0;
  const opacity = typeof layer.opacity === 'number' ? layer.opacity : 1;

  if (layer.type === 'text' && layer.text) {
    const node = figma.createText();
    parent.appendChild(node);
    node.fontName = await resolveFont(layer.fontFamily, layer.fontWeight);
    node.characters = String(layer.text);
    node.fontSize = Math.max(1, Number(layer.fontSize) || 16);
    const color = parseCssColor(layer.color);
    if (color) node.fills = [solidFill(color)];
    const lineHeight = Number(layer.lineHeight) || 0;
    node.lineHeight = lineHeight > 0 ? { value: lineHeight, unit: 'PIXELS' } : { unit: 'AUTO' };
    const letterSpacing = Number(layer.letterSpacing) || 0;
    if (letterSpacing) node.letterSpacing = { value: letterSpacing, unit: 'PIXELS' };
    node.textAlignHorizontal = alignOf(layer.align);
    node.name = layer.name || 'texto';

    if (height > node.fontSize * 1.8) {
      node.textAutoResize = 'HEIGHT';
      node.resize(Math.max(1, width), 1);
    }
    node.x = x;
    node.y = y;
    if (opacity < 1) node.opacity = opacity;
    return node;
  }

  const rect = figma.createRectangle();
  parent.appendChild(rect);
  rect.resize(Math.max(1, width), Math.max(1, height));
  rect.name = layer.name || (layer.type === 'image' ? 'imagem' : 'camada');
  if (radius) rect.cornerRadius = radius;

  if (layer.type === 'image' && layer.src) {
    const image = await loadImage(layer.src);
    if (image) {
      rect.fills = [{ type: 'IMAGE', imageHash: image.hash, scaleMode: 'FILL' }];
    } else {
      rect.fills = [solidFill({ hex: '#d4d4d8', alpha: 1 })];
      rect.opacity = 0.35;
    }
  } else {
    const fill = parseCssColor(layer.fill);
    rect.fills = fill
      ? [solidFill({ hex: fill.hex, alpha: typeof layer.fillOpacity === 'number' ? layer.fillOpacity : fill.alpha })]
      : [];
    const border = layer.border;
    if (border && Number(border.width) > 0) {
      const borderColor = parseCssColor(border.color);
      if (borderColor) {
        rect.strokes = [solidFill(borderColor)];
        rect.strokeWeight = Number(border.width);
        rect.strokeAlign = 'INSIDE';
      }
    }
    if (opacity < 1) rect.opacity = opacity;
  }

  rect.x = x;
  rect.y = y;
  return rect;
}

async function resolveFont(family, weight) {
  const familyName = String(family || 'Inter').replace(/["']/g, '').split(',')[0].trim() || 'Inter';
  const numeric = normalizeWeight(weight);
  const styleName = STYLE_BY_WEIGHT[numeric] || 'Regular';
  const candidates = [
    { family: familyName, style: styleName },
    { family: familyName, style: 'Regular' },
    { family: 'Inter', style: styleName },
    { family: 'Inter', style: 'Regular' },
  ];
  for (const candidate of candidates) {
    try {
      await figma.loadFontAsync(candidate);
      return candidate;
    } catch (error) {
      /* fonte indisponível: tenta a próxima */
    }
  }
  throw new Error('Nenhuma fonte disponível para o texto.');
}

async function loadImage(src) {
  if (imageCache.has(src)) return imageCache.get(src);
  let image = null;
  try {
    const response = await fetch(src);
    if (response.ok) {
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > 0) image = figma.createImage(new Uint8Array(buffer));
    }
  } catch (error) {
    image = null;
  }
  imageCache.set(src, image);
  return image;
}

function normalizeWeight(weight) {
  const value = Number(weight) || 400;
  const keys = Object.keys(STYLE_BY_WEIGHT).map(Number);
  return keys.reduce((closest, current) =>
    Math.abs(current - value) < Math.abs(closest - value) ? current : closest,
  );
}

function alignOf(align) {
  if (align === 'center') return 'CENTER';
  if (align === 'right') return 'RIGHT';
  if (align === 'justify') return 'JUSTIFIED';
  return 'LEFT';
}

function parseCssColor(value) {
  if (!value) return null;
  const text = String(value).trim().toLowerCase();
  if (!text || text === 'transparent') return null;

  const fn = text.match(/^rgba?\(([^)]+)\)$/);
  if (fn) {
    const parts = fn[1].split(',').map((part) => parseFloat(part.trim()));
    if (parts.length < 3 || parts.some((part) => !Number.isFinite(part))) return null;
    return {
      r: clamp01(parts[0] / 255),
      g: clamp01(parts[1] / 255),
      b: clamp01(parts[2] / 255),
      alpha: parts.length > 3 ? clamp01(parts[3]) : 1,
    };
  }

  const hex = text.match(/^#([0-9a-f]{3,8})$/);
  if (!hex) return null;
  const raw = hex[1];
  const expand = (chunk) => parseInt(chunk.length === 1 ? chunk + chunk : chunk, 16) / 255;
  if (raw.length === 3 || raw.length === 4) {
    return {
      r: expand(raw[0]),
      g: expand(raw[1]),
      b: expand(raw[2]),
      alpha: raw.length === 4 ? expand(raw[3]) : 1,
    };
  }
  if (raw.length === 6 || raw.length === 8) {
    return {
      r: expand(raw.slice(0, 2)),
      g: expand(raw.slice(2, 4)),
      b: expand(raw.slice(4, 6)),
      alpha: raw.length === 8 ? expand(raw.slice(6, 8)) : 1,
    };
  }
  return null;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

function solidFill(color) {
  return {
    type: 'SOLID',
    color: { r: color.r, g: color.g, b: color.b },
    opacity: typeof color.alpha === 'number' ? color.alpha : 1,
  };
}
