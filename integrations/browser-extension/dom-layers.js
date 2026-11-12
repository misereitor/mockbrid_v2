/**
 * Extrator de camadas executado dentro da página capturada.
 *
 * Gera o mesmo formato de camada do Mockbird (`mockbird.design-bundle/v1`):
 * retângulos, textos e imagens em coordenadas absolutas da página.
 * A cópia do extrator usada pelo editor fica em
 * `frontend/src/lib/designBundle.ts`.
 */
(function () {
  'use strict';

  var SKIP_TAGS = {
    SCRIPT: true,
    STYLE: true,
    LINK: true,
    META: true,
    NOSCRIPT: true,
    TEMPLATE: true,
    HEAD: true,
    TITLE: true,
    BR: true,
    OPTION: true,
  };

  var MAX_LAYERS = 4000;

  function round(value) {
    return Math.round(value * 100) / 100;
  }

  function toHex(value) {
    var clamped = Math.max(0, Math.min(255, Math.round(value)));
    return clamped.toString(16).padStart(2, '0');
  }

  function parseColor(value) {
    if (!value) return null;
    var text = String(value).trim().toLowerCase();
    if (!text || text === 'transparent' || text === 'none') return null;

    var fn = text.match(/^rgba?\(([^)]+)\)$/);
    if (fn) {
      var parts = fn[1].split(',').map(function (part) {
        return parseFloat(part.trim());
      });
      if (parts.length < 3) return null;
      var alpha = parts.length > 3 ? parts[3] : 1;
      if (!Number.isFinite(alpha) || alpha <= 0) return null;
      return {
        hex: '#' + toHex(parts[0]) + toHex(parts[1]) + toHex(parts[2]),
        alpha: Math.round(alpha * 100) / 100,
      };
    }

    var hex = text.match(/^#([0-9a-f]{3,8})$/);
    if (!hex) return null;
    var raw = hex[1];
    if (raw.length === 3) return { hex: '#' + raw[0] + raw[0] + raw[1] + raw[1] + raw[2] + raw[2], alpha: 1 };
    if (raw.length === 6) return { hex: '#' + raw, alpha: 1 };
    if (raw.length === 8) {
      var a = parseInt(raw.slice(6, 8), 16) / 255;
      if (a <= 0) return null;
      return { hex: '#' + raw.slice(0, 6), alpha: Math.round(a * 100) / 100 };
    }
    return null;
  }

  function firstGradientColor(backgroundImage) {
    if (!backgroundImage || backgroundImage.indexOf('gradient') === -1) return null;
    var matches = backgroundImage.match(/rgba?\([^)]+\)|#[0-9a-f]{3,8}/gi) || [];
    for (var i = 0; i < matches.length; i += 1) {
      var parsed = parseColor(matches[i]);
      if (parsed) return parsed;
    }
    return null;
  }

  function px(value) {
    var parsed = parseFloat(value || '');
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function describe(el) {
    var tag = el.tagName.toLowerCase();
    if (el.id) return tag + '#' + el.id;
    var classes = (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 2);
    return classes.length ? tag + '.' + classes.join('.') : tag;
  }

  function firstFontFamily(value) {
    var first = (value || '').split(',')[0] || 'Inter';
    return first.replace(/["']/g, '').trim() || 'Inter';
  }

  function alignmentOf(value) {
    if (value === 'center' || value === 'right' || value === 'justify') return value;
    return 'left';
  }

  function capture() {
    var scrollX = window.scrollX || 0;
    var scrollY = window.scrollY || 0;
    var width = Math.max(1, document.documentElement.clientWidth || window.innerWidth);
    var height = Math.max(
      1,
      Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement.scrollHeight,
        window.innerHeight,
      ),
    );

    var layers = [];
    var overflow = false;

    function add(layer) {
      if (layers.length >= MAX_LAYERS) {
        overflow = true;
        return;
      }
      if (!Number.isFinite(layer.x) || !Number.isFinite(layer.y)) return;
      if (layer.width < 1 || layer.height < 1) return;
      layer.x = round(layer.x);
      layer.y = round(layer.y);
      layer.width = round(layer.width);
      layer.height = round(layer.height);
      layers.push(layer);
    }

    function visit(el, depth) {
      if (depth > 40) return;
      var tag = el.tagName.toUpperCase();
      if (SKIP_TAGS[tag]) return;

      var style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return;
      var opacity = parseFloat(style.opacity);
      if (Number.isFinite(opacity) && opacity === 0) return;

      var rect = el.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) {
        for (var c = 0; c < el.children.length; c += 1) visit(el.children[c], depth + 1);
        return;
      }

      var name = describe(el);
      var x = rect.left + scrollX;
      var y = rect.top + scrollY;

      if (tag === 'SVG') {
        try {
          var markup = new XMLSerializer().serializeToString(el);
          add({
            type: 'image',
            name: name,
            x: x,
            y: y,
            width: rect.width,
            height: rect.height,
            src: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(markup),
            opacity: opacity < 1 ? round(opacity) : undefined,
          });
        } catch (error) {
          /* svg não serializável */
        }
        return;
      }

      if (tag === 'IMG') {
        var src = el.currentSrc || el.getAttribute('src') || '';
        if (src) {
          add({
            type: 'image',
            name: name,
            x: x,
            y: y,
            width: rect.width,
            height: rect.height,
            src: src,
            radius: px(style.borderTopLeftRadius) || undefined,
            opacity: opacity < 1 ? round(opacity) : undefined,
          });
        }
        return;
      }

      var solidBackground = parseColor(style.backgroundColor);
      var background = solidBackground || firstGradientColor(style.backgroundImage);
      var borderWidth = px(style.borderTopWidth);
      var borderColor = parseColor(style.borderTopColor);
      var hasBorder = borderWidth > 0 && !!borderColor && style.borderTopStyle !== 'none';
      var radius = px(style.borderTopLeftRadius);

      // O fundo do body já vira o preenchimento do frame (`screen.background`).
      if ((background || hasBorder) && !(tag === 'BODY' && solidBackground && !hasBorder)) {
        add({
          type: 'rect',
          name: name,
          x: x,
          y: y,
          width: rect.width,
          height: rect.height,
          fill: background ? background.hex : undefined,
          fillOpacity: background ? background.alpha : undefined,
          radius: radius || undefined,
          border: hasBorder && borderColor ? { color: borderColor.hex, width: round(borderWidth) } : undefined,
          opacity: opacity < 1 ? round(opacity) : undefined,
        });
      }

      var fontSize = px(style.fontSize);
      var paddingLeft = px(style.paddingLeft);
      var paddingRight = px(style.paddingRight);
      var lineHeight = px(style.lineHeight);
      var color = parseColor(style.color);

      if (fontSize > 0) {
        for (var n = 0; n < el.childNodes.length; n += 1) {
          var node = el.childNodes[n];
          if (node.nodeType !== 3) continue;
          var raw = (node.textContent || '').replace(/\s+/g, ' ').trim();
          if (!raw) continue;

          var box;
          try {
            var range = document.createRange();
            range.selectNodeContents(node);
            box = range.getBoundingClientRect();
          } catch (error) {
            box = rect;
          }
          if (box.width < 1 || box.height < 1) continue;

          var lineBox = lineHeight > 0 ? lineHeight : fontSize * 1.4;
          var wrapped = box.height > lineBox * 1.8;

          add({
            type: 'text',
            name: name + ' · texto',
            x: (wrapped ? rect.left : box.left) + scrollX,
            y: box.top + scrollY,
            width: wrapped ? Math.max(1, rect.width - paddingLeft - paddingRight) : box.width,
            height: Math.min(box.height, Math.max(lineBox, fontSize)),
            text: raw.length > 2000 ? raw.slice(0, 2000) + '…' : raw,
            color: color ? color.hex : undefined,
            fontSize: round(fontSize),
            fontWeight: parseInt(style.fontWeight, 10) || 400,
            fontFamily: firstFontFamily(style.fontFamily),
            lineHeight: lineHeight > 0 ? round(lineHeight) : 0,
            letterSpacing: style.letterSpacing === 'normal' ? 0 : round(px(style.letterSpacing)),
            align: alignmentOf(style.textAlign),
            opacity: opacity < 1 ? round(opacity) : undefined,
          });
        }
      }

      for (var child = 0; child < el.children.length; child += 1) {
        visit(el.children[child], depth + 1);
      }
    }

    if (document.body) visit(document.body, 0);

    var bodyBackground = parseColor(window.getComputedStyle(document.body || document.documentElement).backgroundColor);

    return {
      id: 'capture-' + Date.now().toString(36),
      name: (document.title || location.hostname || 'Página capturada').trim().slice(0, 120),
      width: width,
      height: height,
      device_type: 'desktop',
      background: bodyBackground ? bodyBackground.hex : '#ffffff',
      url: location.href,
      html: document.documentElement.outerHTML.slice(0, 400000),
      css: '',
      layers: layers,
      truncated: overflow,
    };
  }

  window.__mockbirdCapturePage = capture;
})();
