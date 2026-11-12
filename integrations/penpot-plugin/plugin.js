/**
 * Plugin do Penpot que reconstrói um bundle exportado pelo Mockbird
 * (`mockbird.design-bundle/v1`) como boards com camadas editáveis.
 *
 * A interface (seletor de arquivo) vai embutida como data URI para o plugin
 * funcionar de qualquer host — veja `docs/design-bundle.md`.
 */

var UI_HTML = String.raw`<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <title>Mockbird Import</title>
    <style>
      * { box-sizing: border-box; }
      body {
        margin: 0;
        padding: 16px;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 12px;
        background: #1f1f24;
        color: #f4f4f5;
        display: flex;
        flex-direction: column;
        gap: 12px;
        height: 100vh;
      }
      h1 { margin: 0; font-size: 13px; font-weight: 600; }
      p { margin: 0; color: #a1a1aa; line-height: 1.5; }
      .drop {
        border: 1px dashed #52525b;
        border-radius: 8px;
        padding: 14px;
        text-align: center;
        background: #27272a;
        cursor: pointer;
        transition: border-color 0.15s;
      }
      .drop:hover, .drop.over { border-color: #2dd4bf; }
      .drop strong { display: block; margin-bottom: 2px; }
      #file { display: none; }
      textarea {
        flex: 1;
        min-height: 110px;
        width: 100%;
        resize: none;
        padding: 8px;
        border-radius: 8px;
        border: 1px solid #3f3f46;
        background: #27272a;
        color: #f4f4f5;
        font-family: ui-monospace, Menlo, Consolas, monospace;
        font-size: 11px;
        line-height: 1.5;
      }
      textarea:focus { outline: 1px solid #2dd4bf; }
      button {
        border: 0;
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 12px;
        font-weight: 600;
        color: #04211e;
        background: #2dd4bf;
        cursor: pointer;
      }
      button:disabled { opacity: 0.55; cursor: default; }
      .status { min-height: 16px; font-size: 11px; line-height: 1.5; color: #a1a1aa; }
      .status.error { color: #f87171; }
      .status.ok { color: #4ade80; }
      .warnings { margin: 0; padding-left: 16px; color: #a1a1aa; max-height: 72px; overflow: auto; }
    </style>
  </head>
  <body>
    <h1>Importar telas do Mockbird</h1>
    <p>No Mockbird, abra o projeto e clique em <strong>Figma/Penpot</strong> para baixar o .mockbird.json.</p>

    <label class="drop" id="drop">
      <input type="file" id="file" accept=".json,application/json" />
      <strong>Escolher arquivo</strong>
      <span>ou arraste o .mockbird.json aqui</span>
    </label>

    <textarea id="json" spellcheck="false" placeholder="...ou cole o conteúdo do bundle aqui"></textarea>
    <button id="run" disabled>Importar para o Penpot</button>
    <div class="status" id="status"></div>
    <ul class="warnings" id="warnings" style="display:none"></ul>

    <script>
      var drop = document.getElementById('drop');
      var fileInput = document.getElementById('file');
      var jsonInput = document.getElementById('json');
      var runButton = document.getElementById('run');
      var statusEl = document.getElementById('status');
      var warningsEl = document.getElementById('warnings');

      function setStatus(text, kind) {
        statusEl.textContent = text || '';
        statusEl.className = 'status' + (kind ? ' ' + kind : '');
      }

      function refresh() {
        runButton.disabled = !jsonInput.value.trim();
      }

      function readFile(file) {
        if (!file) return;
        file.text().then(function (text) {
          jsonInput.value = text;
          refresh();
          try {
            var parsed = JSON.parse(text);
            var screens = Array.isArray(parsed.screens) ? parsed.screens.length : 0;
            setStatus(screens ? screens + ' tela(s) no arquivo.' : 'Arquivo sem telas.', screens ? 'ok' : 'error');
          } catch (error) {
            setStatus('JSON inválido: ' + error.message, 'error');
          }
        });
      }

      drop.addEventListener('click', function () { fileInput.click(); });
      fileInput.addEventListener('change', function () { readFile(fileInput.files && fileInput.files[0]); });
      jsonInput.addEventListener('input', refresh);

      ['dragenter', 'dragover'].forEach(function (name) {
        drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add('over'); });
      });
      ['dragleave', 'drop'].forEach(function (name) {
        drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.remove('over'); });
      });
      drop.addEventListener('drop', function (event) {
        readFile(event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]);
      });

      runButton.addEventListener('click', function () {
        var raw = jsonInput.value.trim();
        if (!raw) return;
        runButton.disabled = true;
        warningsEl.style.display = 'none';
        warningsEl.innerHTML = '';
        setStatus('Importando...');
        parent.postMessage({ type: 'import', json: raw }, '*');
      });

      window.addEventListener('message', function (event) {
        if (event.source !== window.parent) return;
        var message = event.data;
        if (!message || !message.type) return;
        if (message.type === 'progress') {
          setStatus('Importando tela ' + message.done + ' de ' + message.total + '...');
          return;
        }
        if (message.type === 'done') {
          var skipped = message.skipped ? ' (' + message.skipped + ' camada(s) ignorada(s))' : '';
          setStatus(message.screens + ' tela(s) e ' + message.layers + ' camada(s) importadas' + skipped + '.', 'ok');
          if (Array.isArray(message.warnings) && message.warnings.length) {
            warningsEl.style.display = 'block';
            message.warnings.forEach(function (text) {
              var item = document.createElement('li');
              item.textContent = text;
              warningsEl.appendChild(item);
            });
          }
          runButton.disabled = false;
          return;
        }
        if (message.type === 'error') {
          setStatus(message.message, 'error');
          runButton.disabled = false;
        }
      });
    </script>
  </body>
</html>`;

var GAP_BETWEEN_BOARDS = 120;

function send(payload) {
  try {
    penpot.ui.sendMessage(payload);
  } catch (error) {
    console.error('[Mockbird] falha ao enviar mensagem para a UI', error);
  }
}

try {
  penpot.ui.open('Mockbird Import', 'data:text/html;charset=utf-8,' + encodeURIComponent(UI_HTML), {
    width: 460,
    height: 600,
  });
} catch (error) {
  console.error('[Mockbird] falha ao abrir a interface do plugin', error);
}

if (typeof penpot.ui.onMessage === 'function') {
  penpot.ui.onMessage(function (message) {
    var data = message && message.pluginMessage ? message.pluginMessage : message;
    if (!data || data.type !== 'import') return;
    importBundle(data.json);
  });
}

async function importBundle(rawJson) {
  try {
    var bundle = JSON.parse(rawJson);
    if (!bundle || bundle.format !== 'mockbird.design-bundle') {
      throw new Error('Arquivo inválido: esperado um bundle do Mockbird (format "mockbird.design-bundle").');
    }
    var screens = Array.isArray(bundle.screens) ? bundle.screens : [];
    if (!screens.length) throw new Error('O bundle não contém telas.');

    var cursorX = 0;
    var layers = 0;
    var skipped = 0;
    var warnings = [];

    for (var index = 0; index < screens.length; index += 1) {
      var screen = screens[index];
      var width = Math.max(1, Math.round(Number(screen.width) || 1440));
      var height = Math.max(1, Math.round(Number(screen.height) || 900));

      var board = penpot.createBoard();
      board.name = String(screen.name || 'Tela ' + (index + 1));
      board.resize(width, height);
      board.x = cursorX;
      board.y = 0;
      try {
        board.clipContent = true;
      } catch (error) {
        /* versões antigas não expõem clipContent */
      }
      board.fills = [{ fillColor: normalizeColor(screen.background) || '#ffffff', fillOpacity: 1 }];
      cursorX += width + GAP_BETWEEN_BOARDS;

      var screenLayers = Array.isArray(screen.layers) ? screen.layers : [];
      for (var layerIndex = 0; layerIndex < screenLayers.length; layerIndex += 1) {
        try {
          await createLayer(board, screenLayers[layerIndex]);
          layers += 1;
        } catch (error) {
          skipped += 1;
          if (warnings.length < 8) {
            warnings.push(String(screen.name || 'tela') + ' → ' + String((error && error.message) || error));
          }
        }
      }

      send({ type: 'progress', done: index + 1, total: screens.length });
    }

    send({
      type: 'done',
      screens: screens.length,
      layers: layers,
      skipped: skipped,
      warnings: warnings,
    });
  } catch (error) {
    send({ type: 'error', message: String((error && error.message) || error) });
  }
}

async function createLayer(board, layer) {
  var x = board.x + (Number(layer.x) || 0);
  var y = board.y + (Number(layer.y) || 0);
  var width = Math.max(1, Number(layer.width) || 1);
  var height = Math.max(1, Number(layer.height) || 1);

  if (layer.type === 'text' && layer.text) {
    var text = penpot.createText(String(layer.text));
    if (!text) throw new Error('não foi possível criar o texto');
    board.appendChild(text);
    try {
      text.growType = 'auto-height';
    } catch (error) {
      /* mantém o padrão */
    }
    text.fontSize = String(Math.max(1, Math.round(Number(layer.fontSize) || 16)));
    if (layer.fontFamily) {
      try {
        text.fontFamily = String(layer.fontFamily);
      } catch (error) {
        /* fonte não disponível no Penpot */
      }
    }
    if (layer.fontWeight) {
      try {
        text.fontWeight = String(layer.fontWeight);
      } catch (error) {
        /* peso não suportado */
      }
    }
    var color = normalizeColor(layer.color);
    if (color) text.fills = [{ fillColor: color, fillOpacity: 1 }];
    if (Number(layer.letterSpacing)) {
      try {
        text.letterSpacing = Number(layer.letterSpacing);
      } catch (error) {
        /* propriedade não disponível */
      }
    }
    if (Number(layer.lineHeight) > 0) {
      try {
        text.lineHeight = Number(layer.lineHeight);
      } catch (error) {
        /* propriedade não disponível */
      }
    }
    if (layer.align) {
      try {
        text.align = layer.align === 'justify' ? 'justify' : layer.align;
      } catch (error) {
        /* alinhamento não suportado */
      }
    }
    try {
      text.resize(width, height);
    } catch (error) {
      /* tamanho mínimo do Penpot */
    }
    text.name = layer.name || 'texto';
    if (typeof layer.opacity === 'number') {
      try {
        text.opacity = layer.opacity;
      } catch (error) {
        /* opacidade não suportada */
      }
    }
    text.x = x;
    text.y = y;
    return text;
  }

  var rect = penpot.createRectangle();
  board.appendChild(rect);
  rect.resize(width, height);
  rect.name = layer.name || (layer.type === 'image' ? 'imagem' : 'camada');
  if (Number(layer.radius) > 0) {
    try {
      rect.borderRadius = Number(layer.radius);
    } catch (error) {
      /* raio não suportado */
    }
  }

  if (layer.type === 'image' && layer.src) {
    var image = null;
    try {
      image = await penpot.uploadMediaUrl('mockbird-image', String(layer.src));
    } catch (error) {
      image = null;
    }
    rect.fills = image
      ? [{ fillOpacity: 1, fillImage: image }]
      : [{ fillColor: '#d4d4d8', fillOpacity: 0.5 }];
  } else {
    var fill = normalizeColor(layer.fill);
    var fillOpacity = typeof layer.fillOpacity === 'number' ? layer.fillOpacity : 1;
    rect.fills = fill ? [{ fillColor: fill, fillOpacity: fillOpacity }] : [];
    if (layer.border && Number(layer.border.width) > 0) {
      var borderColor = normalizeColor(layer.border.color);
      if (borderColor) {
        rect.strokes = [
          {
            strokeColor: borderColor,
            strokeOpacity: 1,
            strokeStyle: 'solid',
            strokeWidth: Number(layer.border.width),
            strokeAlignment: 'inner',
          },
        ];
      }
    }
  }

  if (typeof layer.opacity === 'number') {
    try {
      rect.opacity = layer.opacity;
    } catch (error) {
      /* opacidade não suportada */
    }
  }
  rect.x = x;
  rect.y = y;
  return rect;
}

/** Converte `rgb()`/`rgba()`/hex para `#rrggbb` (o Penpot usa fillColor + fillOpacity). */
function normalizeColor(value) {
  if (!value) return null;
  var text = String(value).trim().toLowerCase();
  if (!text || text === 'transparent' || text === 'none') return null;

  var fn = text.match(/^rgba?\(([^)]+)\)$/);
  if (fn) {
    var parts = fn[1].split(',').map(function (part) {
      return parseFloat(part.trim());
    });
    if (parts.length < 3 || parts.some(function (part) { return !Number.isFinite(part); })) return null;
    return '#' + toHex(parts[0]) + toHex(parts[1]) + toHex(parts[2]);
  }

  var hex = text.match(/^#([0-9a-f]{3,8})$/);
  if (!hex) return null;
  var raw = hex[1];
  if (raw.length === 3) return '#' + raw[0] + raw[0] + raw[1] + raw[1] + raw[2] + raw[2];
  if (raw.length === 6) return '#' + raw;
  if (raw.length === 8) return '#' + raw.slice(0, 6);
  return null;
}

function toHex(value) {
  var clamped = Math.max(0, Math.min(255, Math.round(value)));
  return clamped.toString(16).padStart(2, '0');
}
