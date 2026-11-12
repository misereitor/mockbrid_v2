/**
 * Popup da extensão: injeta o extrator de camadas na aba ativa e monta um
 * bundle `mockbird.design-bundle/v1` com uma tela (a página capturada).
 */

const captureButton = document.getElementById('capture');
const downloadButton = document.getElementById('download');
const copyButton = document.getElementById('copy');
const statusEl = document.getElementById('status');

let currentBundle = null;
let currentHost = 'pagina';

function setStatus(text, kind) {
  statusEl.textContent = text || '';
  statusEl.className = 'status' + (kind ? ' ' + kind : '');
}

function slugify(value) {
  return (
    String(value || 'pagina')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'pagina'
  );
}

function buildBundle(screen, tab) {
  const name = (tab && tab.title) || screen.name || 'Página capturada';
  return {
    format: 'mockbird.design-bundle',
    version: 1,
    exported_at: new Date().toISOString(),
    project: { id: 'browser-capture', name: name },
    tokens: { light: {}, dark: {}, shared: {} },
    screens: [
      {
        id: screen.id,
        name: name.slice(0, 120),
        width: screen.width,
        height: screen.height,
        device_type: screen.device_type,
        background: screen.background,
        html: screen.html,
        css: '',
        layers: screen.layers,
      },
    ],
  };
}

function downloadBundle() {
  if (!currentBundle) return;
  const blob = new Blob([JSON.stringify(currentBundle, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = slugify(currentHost) + '.mockbird.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  setStatus('Arquivo baixado. Importe no plugin Figma/Penpot.', 'ok');
}

async function copyBundle() {
  if (!currentBundle) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(currentBundle, null, 2));
    setStatus('JSON copiado para a área de transferência.', 'ok');
  } catch (error) {
    setStatus('Não foi possível copiar: ' + error.message, 'error');
  }
}

async function capturePage() {
  captureButton.disabled = true;
  downloadButton.disabled = true;
  copyButton.disabled = true;
  currentBundle = null;
  setStatus('Capturando…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) throw new Error('Nenhuma aba ativa encontrada.');
    if (!tab.url || !/^https?:/i.test(tab.url)) {
      throw new Error('Esta página não pode ser capturada (apenas http/https).');
    }

    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['dom-layers.js'] });
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.__mockbirdCapturePage(),
    });

    const captured = results && results[0] && results[0].result;
    if (!captured || !Array.isArray(captured.layers)) {
      throw new Error('Não foi possível extrair as camadas da página.');
    }

    currentBundle = buildBundle(captured, tab);
    currentHost = new URL(tab.url).hostname;

    const total = captured.layers.length;
    const truncated = captured.truncated ? ' (limite de camadas atingido)' : '';
    setStatus(`${total} camada(s) capturadas em ${captured.width}×${captured.height}${truncated}.`, 'ok');
    downloadButton.disabled = false;
    copyButton.disabled = false;
  } catch (error) {
    setStatus(String((error && error.message) || error), 'error');
  } finally {
    captureButton.disabled = false;
  }
}

captureButton.addEventListener('click', capturePage);
downloadButton.addEventListener('click', downloadBundle);
copyButton.addEventListener('click', copyBundle);
