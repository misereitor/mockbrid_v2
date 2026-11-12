/**
 * Documento HTML (srcDoc) executado dentro do iframe do canvas.
 *
 * O runtime embutido cuida de seleção (inclusive múltipla, com Shift/Ctrl),
 * edição de texto inline, arrastar para reordenar/mover, alças de
 * redimensionamento, atalhos e do modo interativo. O iframe roda sem
 * `allow-same-origin` (origem opaca): toda comunicação com o editor acontece
 * por `postMessage`.
 */

export interface CanvasDocTokens {
  [key: string]: string;
}

const CANVAS_RUNTIME = `
      <script>
        let selectedEl = null;
        let selectedEls = [];
        let currentMode = 'edit';
        let overlay = null;
        let hoverEl = null;
        let inlineEditing = false;
        let inlineEl = null;
        let inlineOriginal = null;
        let suppressClick = false;
        let dragCandidate = null;
        let dragged = null;
        let dragInfo = null;
        let dropMarker = null;
        let dropTarget = null;

        function post(payload) {
          window.parent.postMessage(payload, '*');
        }

        function rootEl() {
          return document.getElementById('mockbird-root') || document.body;
        }

        function isOverlayTarget(node) {
          return !!(node && node.closest && node.closest('#mb-overlay, #mb-drop-marker'));
        }

        function isFormControl(node) {
          if (!node || !node.tagName) return false;
          return /^(INPUT|TEXTAREA|SELECT|OPTION|VIDEO|AUDIO|IFRAME)$/.test(node.tagName);
        }

        function emitHtmlChanged() {
          const root = rootEl();
          const clone = root.cloneNode(true);
          clone.querySelectorAll('#mb-overlay, #mb-drop-marker').forEach(function (n) { n.remove(); });
          clone.querySelectorAll('.mb-hover, .mb-selected, .mb-editing').forEach(function (n) {
            n.classList.remove('mb-hover', 'mb-selected', 'mb-editing');
          });
          clone.querySelectorAll('[contenteditable]').forEach(function (n) {
            n.removeAttribute('contenteditable');
            n.style.removeProperty('user-select');
          });
          post({ type: 'MOCKBIRD_HTML_CHANGED', html: clone.innerHTML });
        }

        function extractSnippet(target) {
          if (!target) return '';
          const text = (target.innerText || '').trim().replace(/\\s+/g, ' ');
          if (text) return text.length > 36 ? text.substring(0, 36) + '…' : text;
          const img = target.querySelector('img') || (target.tagName.toLowerCase() === 'img' ? target : null);
          if (img && img.src) {
            const parts = img.src.split('/');
            return parts[parts.length - 1].substring(0, 30);
          }
          return '';
        }

        function buildSelector(target) {
          if (!target || target === document.body) return '';
          const tag = target.tagName.toLowerCase();
          const id = target.id ? '#' + target.id : '';
          const classes = Array.from(target.classList || [])
            .filter(function (c) { return c.indexOf('mb-') !== 0; })
            .slice(0, 2)
            .map(function (c) { return '.' + c; })
            .join('');
          return tag + id + classes;
        }

        function ensureOverlay() {
          if (overlay && overlay.isConnected) return overlay;
          overlay = document.createElement('div');
          overlay.id = 'mb-overlay';
          document.body.appendChild(overlay);
          overlay.addEventListener('pointerdown', onHandleDown);
          return overlay;
        }

        // Uma caixa por elemento selecionado; as alças só aparecem com um.
        function positionOverlay() {
          if (!overlay) return;
          const alive = selectedEls.filter(function (el) { return el && el.isConnected; });
          selectedEls = alive;
          if (selectedEl && alive.indexOf(selectedEl) < 0) {
            selectedEl = alive.length ? alive[alive.length - 1] : null;
          }

          overlay.innerHTML = '';
          if (!alive.length || inlineEditing) {
            overlay.style.display = 'none';
            return;
          }
          overlay.style.display = 'block';

          alive.forEach(function (el) {
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) return;
            const box = document.createElement('div');
            box.className = 'mb-box' + (el === selectedEl ? ' mb-box-primary' : '');
            box.style.left = (rect.left + window.scrollX) + 'px';
            box.style.top = (rect.top + window.scrollY) + 'px';
            box.style.width = rect.width + 'px';
            box.style.height = rect.height + 'px';
            if (alive.length === 1) {
              ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach(function (dir) {
                const handle = document.createElement('div');
                handle.className = 'mb-handle';
                handle.setAttribute('data-dir', dir);
                handle.setAttribute('title', 'Redimensionar');
                box.appendChild(handle);
              });
            }
            overlay.appendChild(box);
          });
        }

        function hideOverlay() {
          if (overlay) overlay.style.display = 'none';
        }

        function setHover(el) {
          if (hoverEl === el) return;
          if (hoverEl) hoverEl.classList.remove('mb-hover');
          hoverEl = el;
          if (hoverEl && hoverEl !== selectedEl) hoverEl.classList.add('mb-hover');
        }

        function postSelection() {
          if (!selectedEl) {
            post({ type: 'MOCKBIRD_DESELECT' });
            return;
          }
          const computed = window.getComputedStyle(selectedEl);
          post({
            type: 'MOCKBIRD_ELEMENT_SELECTED',
            mbId: selectedEl.getAttribute('data-mb-id') || selectedEl.tagName.toLowerCase(),
            tag: selectedEl.tagName.toLowerCase(),
            text: selectedEl.innerText || '',
            selector: buildSelector(selectedEl),
            snippet: extractSnippet(selectedEl),
            leaf: selectedEl.children.length === 0 && !isFormControl(selectedEl),
            count: selectedEls.length,
            styles: {
              color: computed.color,
              backgroundColor: computed.backgroundColor,
              padding: computed.padding,
              fontSize: computed.fontSize,
              borderRadius: computed.borderRadius
            }
          });
        }

        function setSelection(list) {
          if (inlineEditing) return;
          const next = [];
          list.forEach(function (el) {
            if (!el || el === document.body || el === document.documentElement) return;
            if (next.indexOf(el) < 0) next.push(el);
          });

          selectedEls.forEach(function (el) {
            if (next.indexOf(el) < 0) el.classList.remove('mb-selected');
          });
          next.forEach(function (el) { el.classList.add('mb-selected'); });

          selectedEls = next;
          selectedEl = next.length ? next[next.length - 1] : null;
          setHover(null);
          ensureOverlay();
          positionOverlay();
          postSelection();
        }

        function selectElement(target) {
          if (inlineEditing) return;
          setSelection(target ? [target] : []);
        }

        function toggleInSelection(target) {
          if (selectedEls.indexOf(target) >= 0) {
            setSelection(selectedEls.filter(function (el) { return el !== target; }));
          } else {
            setSelection(selectedEls.concat([target]));
          }
        }

        // ---------------------------------------------------------------
        // Edição de texto inline (duplo clique)
        // ---------------------------------------------------------------
        function finishInlineEdit(cancel) {
          if (!inlineEditing) return;
          const el = inlineEl;
          const original = inlineOriginal;
          inlineEditing = false;
          inlineEl = null;
          inlineOriginal = null;
          if (!el) return;

          el.removeEventListener('blur', onInlineBlur);
          el.removeAttribute('contenteditable');
          el.classList.remove('mb-editing');
          el.style.removeProperty('user-select');

          if (cancel && original) {
            if (el.isConnected) el.replaceWith(original);
            selectElement(original);
            return;
          }
          emitHtmlChanged();
          if (el.isConnected) selectElement(el);
        }

        function onInlineBlur() {
          finishInlineEdit(false);
        }

        function startInlineEdit(el) {
          if (!el || currentMode !== 'edit' || isFormControl(el) || inlineEditing) return;
          selectElement(el);
          inlineEditing = true;
          inlineEl = el;
          inlineOriginal = el.cloneNode(true);

          el.setAttribute('contenteditable', 'plaintext-only');
          el.classList.add('mb-editing');
          el.classList.add('mb-selected');
          el.style.userSelect = 'text';
          hideOverlay();

          const range = document.createRange();
          range.selectNodeContents(el);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          el.focus();

          el.addEventListener('blur', onInlineBlur);
          el.addEventListener('keydown', function onInlineKey(ev) {
            if (ev.key === 'Escape') {
              ev.preventDefault();
              ev.stopPropagation();
              el.removeEventListener('keydown', onInlineKey);
              el.blur();
              finishInlineEdit(true);
            } else if (ev.key === 'Enter' && !ev.shiftKey) {
              ev.preventDefault();
              el.blur();
            }
          });
        }

        // ---------------------------------------------------------------
        // Arrastar: reordenar (elementos no fluxo) ou mover livremente
        // ---------------------------------------------------------------
        function createDropMarker() {
          if (!dropMarker || !dropMarker.isConnected) {
            dropMarker = document.createElement('div');
            dropMarker.id = 'mb-drop-marker';
            document.body.appendChild(dropMarker);
          }
          dropMarker.style.display = 'none';
        }

        function moveDropMarker(e) {
          if (!dropMarker || !dragged || !dragged.parentElement) return;
          const parent = dragged.parentElement;
          const style = window.getComputedStyle(parent);
          const isFlex = style.display.indexOf('flex') >= 0;
          const horizontal = (isFlex && style.flexDirection.indexOf('row') === 0) ||
            (style.display.indexOf('grid') >= 0 && style.gridAutoFlow.indexOf('column') >= 0);

          let best = null;
          let bestDist = Infinity;
          Array.prototype.forEach.call(parent.children, function (child) {
            if (child === dragged || child.nodeType !== 1) return;
            const rect = child.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            const dist = Math.pow(e.clientX - cx, 2) + Math.pow(e.clientY - cy, 2);
            if (dist < bestDist) {
              bestDist = dist;
              best = { child: child, rect: rect };
            }
          });

          if (!best) {
            dropTarget = null;
            dropMarker.style.display = 'none';
            return;
          }

          const before = horizontal
            ? e.clientX < best.rect.left + best.rect.width / 2
            : e.clientY < best.rect.top + best.rect.height / 2;

          dropTarget = { parent: parent, ref: best.child, before: before };

          dropMarker.style.display = 'block';
          if (horizontal) {
            const x = before ? best.rect.left : best.rect.right;
            dropMarker.style.left = (x + window.scrollX - 1.5) + 'px';
            dropMarker.style.top = (best.rect.top + window.scrollY) + 'px';
            dropMarker.style.width = '3px';
            dropMarker.style.height = best.rect.height + 'px';
          } else {
            const y = before ? best.rect.top : best.rect.bottom;
            dropMarker.style.left = (best.rect.left + window.scrollX) + 'px';
            dropMarker.style.top = (y + window.scrollY - 1.5) + 'px';
            dropMarker.style.width = best.rect.width + 'px';
            dropMarker.style.height = '3px';
          }
        }

        function beginDrag(e) {
          const startEl = dragCandidate.el;
          // Arrastar um item da seleção move o grupo inteiro.
          const group = (selectedEls.length > 1 && selectedEls.indexOf(startEl) >= 0)
            ? selectedEls.slice()
            : [startEl];
          const singleStatic = group.length === 1 && window.getComputedStyle(startEl).position === 'static';

          dragged = startEl;
          // O movimento conta a partir do pointerdown: o elemento segue o cursor
          // desde o ponto em que o arraste começou.
          dragInfo = {
            startX: dragCandidate.x,
            startY: dragCandidate.y,
            moved: false,
            singleStatic: singleStatic,
            items: []
          };

          group.forEach(function (el) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            let left = parseFloat(style.left);
            let top = parseFloat(style.top);
            if (isNaN(left)) left = null;
            if (isNaN(top)) top = null;

            if (singleStatic) {
              dragInfo.items.push({ el: el, rect: rect, position: style.position, left: null, top: null, reset: null });
              return;
            }

            // Elementos no fluxo passam a ser posicionados relativamente para mover junto.
            let reset = null;
            if (style.position === 'static') {
              reset = { position: el.style.position, left: el.style.left, top: el.style.top };
              el.style.position = 'relative';
              el.style.left = '0px';
              el.style.top = '0px';
              left = 0;
              top = 0;
            } else {
              const parent = el.offsetParent;
              const parentRect = parent ? parent.getBoundingClientRect() : { left: 0, top: 0 };
              if (left === null) left = rect.left - parentRect.left;
              if (top === null) top = rect.top - parentRect.top;
            }
            dragInfo.items.push({ el: el, rect: rect, position: style.position, left: left, top: top, reset: reset });
          });

          setHover(null);
          hideOverlay();
          document.body.classList.add('mb-dragging');
          try { document.documentElement.setPointerCapture(e.pointerId); } catch (err) {}

          if (singleStatic) createDropMarker();
        }

        function updateDrag(e) {
          if (!dragged || !dragInfo) return;
          const dx = e.clientX - dragInfo.startX;
          const dy = e.clientY - dragInfo.startY;
          if (Math.abs(dx) + Math.abs(dy) > 2) dragInfo.moved = true;

          if (dragInfo.singleStatic) {
            moveDropMarker(e);
            return;
          }

          dragInfo.items.forEach(function (item) {
            item.el.style.left = (item.left + dx) + 'px';
            item.el.style.top = (item.top + dy) + 'px';
          });
          positionOverlay();
        }

        function endDrag() {
          const info = dragInfo;
          const items = info ? info.items.slice() : [];
          const target = dropTarget;
          const moved = !!(info && info.moved);

          document.body.classList.remove('mb-dragging');
          if (dropMarker) dropMarker.style.display = 'none';

          dragged = null;
          dragInfo = null;
          dropTarget = null;
          dragCandidate = null;

          if (!items.length) return;

          if (!moved) {
            // Só o preparo do arraste mexeu nos estilos: devolve tudo.
            items.forEach(function (item) {
              if (!item.reset) return;
              item.el.style.position = item.reset.position;
              item.el.style.left = item.reset.left;
              item.el.style.top = item.reset.top;
            });
            positionOverlay();
            return;
          }

          if (info.singleStatic && target) {
            let ref = target.ref;
            if (!target.before) ref = ref.nextSibling;
            if (ref !== items[0].el) target.parent.insertBefore(items[0].el, ref);
          }

          emitHtmlChanged();
          suppressClick = true;
          setTimeout(function () { suppressClick = false; }, 80);
          setSelection(items.map(function (item) { return item.el; }));
        }

        // ---------------------------------------------------------------
        // Redimensionar pelas alças
        // ---------------------------------------------------------------
        function onHandleDown(e) {
          if (!selectedEl) return;
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();

          const dir = e.target.getAttribute('data-dir') || '';
          const el = selectedEl;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          const start = {
            x: e.clientX,
            y: e.clientY,
            width: rect.width,
            height: rect.height,
            left: parseFloat(style.left),
            top: parseFloat(style.top),
            position: style.position
          };
          if (isNaN(start.left)) start.left = 0;
          if (isNaN(start.top)) start.top = 0;
          if (style.display === 'inline') el.style.display = 'inline-block';

          try { e.target.setPointerCapture(e.pointerId); } catch (err) {}

          function onMove(ev) {
            const dx = ev.clientX - start.x;
            const dy = ev.clientY - start.y;
            let width = start.width;
            let height = start.height;

            if (dir.indexOf('e') >= 0) width = start.width + dx;
            if (dir.indexOf('w') >= 0) width = start.width - dx;
            if (dir.indexOf('s') >= 0) height = start.height + dy;
            if (dir.indexOf('n') >= 0) height = start.height - dy;

            if (dir.indexOf('e') >= 0 || dir.indexOf('w') >= 0) {
              el.style.width = Math.max(8, width) + 'px';
            }
            if (dir.indexOf('s') >= 0 || dir.indexOf('n') >= 0) {
              el.style.height = Math.max(8, height) + 'px';
            }

            if (start.position !== 'static') {
              if (dir.indexOf('w') >= 0) el.style.left = (start.left + dx) + 'px';
              if (dir.indexOf('n') >= 0) el.style.top = (start.top + dy) + 'px';
            }
            positionOverlay();
          }

          function onUp() {
            document.removeEventListener('pointermove', onMove, true);
            document.removeEventListener('pointerup', onUp, true);
            emitHtmlChanged();
            setSelection([el]);
          }

          document.addEventListener('pointermove', onMove, true);
          document.addEventListener('pointerup', onUp, true);
        }

        // ---------------------------------------------------------------
        // Modo edição x interativo
        // ---------------------------------------------------------------
        function applyMode(mode) {
          currentMode = mode === 'interactive' ? 'interactive' : 'edit';
          document.body.classList.toggle('mb-interactive', currentMode === 'interactive');
          document.body.classList.remove('mb-dragging');          if (inlineEditing) finishInlineEdit(false);
          setHover(null);
          // A seleção feita com Shift/Ctrl continua válida nos dois modos.
          positionOverlay();
        }

        // ---------------------------------------------------------------
        // Eventos
        // ---------------------------------------------------------------
        document.addEventListener('pointerdown', function () {
          post({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' });
        }, true);

        document.addEventListener('pointerover', function (e) {
          if (currentMode !== 'edit' || inlineEditing) return;
          const node = e.target;
          if (!node || node.nodeType !== 1 || node === document.body || node === document.documentElement || isOverlayTarget(node)) return;
          setHover(node.closest('[data-mb-id]') || node);
        }, true);

        document.addEventListener('mouseout', function (e) {
          if (!e.relatedTarget) setHover(null);
        });

        // Destino de um clique no modo mock: data-go ou link para outra tela.
        function mockTarget(node) {
          if (!node || !node.closest) return null;
          const goEl = node.closest('[data-go]');
          if (goEl) {
            const value = (goEl.getAttribute('data-go') || '').trim();
            if (value) return { kind: 'screen', target: value };
          }
          const link = node.closest('a[href]');
          if (!link || link.hasAttribute('download')) return null;
          const href = (link.getAttribute('href') || '').trim();
          if (!href || href.charAt(0) === '#') return null;
          if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.indexOf('//') === 0) {
            return { kind: 'external', target: href };
          }
          if (!/\.html?$/i.test(href.split(/[?#]/)[0])) return null;
          return { kind: 'screen', target: href };
        }

        // Clique: no modo mock age como na página; Shift/Ctrl seleciona e
        // acumula elementos (em qualquer modo). No modo edição, clique seleciona.
        document.addEventListener('click', function (e) {
          post({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' });
          if (inlineEditing || suppressClick || isOverlayTarget(e.target)) return;

          const target = e.target.closest('[data-mb-id]') || e.target;
          const isCanvasNode = target && target !== document.body && target !== document.documentElement;
          const additive = e.shiftKey || e.ctrlKey || e.metaKey;

          if (currentMode === 'edit' || additive) {
            if (isCanvasNode) {
              e.preventDefault();
              e.stopPropagation();
              if (additive) toggleInSelection(target);
              else selectElement(target);
            } else if (!additive) {
              selectElement(null);
            }
            return;
          }

          const nav = mockTarget(e.target);
          if (nav) {
            e.preventDefault();
            post({ type: 'MOCKBIRD_NAVIGATE', target: nav.target, external: nav.kind === 'external' });
            return;
          }
          if (!isCanvasNode) selectElement(null);
        }, true);

        // Formulário no mock não navega nem envia nada: só troca de tela via data-go/action.
        document.addEventListener('submit', function (e) {
          e.preventDefault();
          e.stopPropagation();
          const form = e.target;
          if (!form || !form.getAttribute) return;
          const go = (form.getAttribute('data-go') || form.getAttribute('action') || '').trim();
          if (/\.html?$/i.test(go.split(/[?#]/)[0])) {
            post({ type: 'MOCKBIRD_NAVIGATE', target: go, external: false });
          }
        }, true);

        // Duplo clique: texto editável inline (Shift+duplo clique no modo mock).
        document.addEventListener('dblclick', function (e) {
          if (currentMode !== 'edit' && !e.shiftKey) return;
          const node = e.target;
          if (!node || node.nodeType !== 1 || isOverlayTarget(node)) return;
          const target = node.closest('[data-mb-id]') || node;
          if (!target || target === document.body || target === document.documentElement) return;
          e.preventDefault();
          e.stopPropagation();
          if (isFormControl(target)) {
            selectElement(target);
            return;
          }
          startInlineEdit(target);
        }, true);

        // Arrastar para reordenar/mover (no mock, apenas com Shift).
        document.addEventListener('pointerdown', function (e) {
          if (inlineEditing || e.button !== 0) return;
          if (isOverlayTarget(e.target)) return;
          if (currentMode !== 'edit' && !e.shiftKey) return;
          const node = e.target;
          if (!node || node.nodeType !== 1 || node === document.body || node === document.documentElement) return;
          if (isFormControl(node) || node.isContentEditable) return;
          const target = node.closest('[data-mb-id]') || node;
          // Com vários selecionados, Shift+clique em outro elemento ainda adiciona à seleção.
          if (selectedEls.length > 1 && selectedEls.indexOf(target) < 0) return;
          dragCandidate = {
            el: target,
            x: e.clientX,
            y: e.clientY,
            pointerId: e.pointerId
          };
        });

        document.addEventListener('pointermove', function (e) {
          if (dragCandidate && !dragged) {
            if (Math.abs(e.clientX - dragCandidate.x) + Math.abs(e.clientY - dragCandidate.y) < 5) return;
            beginDrag(e);
          }
          if (dragged) updateDrag(e);
        });

        document.addEventListener('pointerup', function () {
          if (dragged) endDrag();
          dragCandidate = null;
        });

        window.addEventListener('pointercancel', function () {
          if (dragged) endDrag();
          dragCandidate = null;
        });

        // Botão direito / contextmenu
        document.addEventListener('contextmenu', function (e) {
          post({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' });
          if (currentMode === 'interactive' || e.shiftKey || e.altKey) return;

          e.preventDefault();
          e.stopPropagation();
          const target = e.target.closest('[data-mb-id]') ||
            (e.target !== document.body && e.target !== document.documentElement ? e.target : null);

          if (target) {
            if (selectedEls.indexOf(target) < 0) selectElement(target);
            post({
              type: 'MOCKBIRD_CONTEXT_MENU',
              kind: 'element',
              clientX: e.clientX,
              clientY: e.clientY,
              target: {
                mbId: target.getAttribute('data-mb-id') || target.tagName.toLowerCase(),
                tag: target.tagName.toLowerCase(),
                selector: buildSelector(target),
                snippet: extractSnippet(target),
                outerHtml: target.outerHTML
              }
            });
          } else {
            selectElement(null);
            post({
              type: 'MOCKBIRD_CONTEXT_MENU',
              kind: 'canvas',
              clientX: e.clientX,
              clientY: e.clientY
            });
          }
        });

        window.addEventListener('wheel', function () {
          post({ type: 'MOCKBIRD_CLOSE_CONTEXT_MENU' });
        }, { passive: true });

        document.addEventListener('scroll', positionOverlay, true);
        window.addEventListener('resize', positionOverlay);
        document.addEventListener('dragstart', function (e) { e.preventDefault(); }, true);

        // Atalhos dentro do canvas: desfazer/refazer, Esc e setas para mover.
        let nudgeTimer = null;
        function scheduleEmit() {
          if (nudgeTimer) clearTimeout(nudgeTimer);
          nudgeTimer = setTimeout(function () {
            nudgeTimer = null;
            emitHtmlChanged();
          }, 220);
        }

        document.addEventListener('keydown', function (e) {
          if (inlineEditing) return;
          const mod = e.ctrlKey || e.metaKey;

          if (mod && (e.key === 'z' || e.key === 'Z')) {
            e.preventDefault();
            post({ type: e.shiftKey ? 'MOCKBIRD_REDO' : 'MOCKBIRD_UNDO' });
            return;
          }
          if (mod && (e.key === 'y' || e.key === 'Y')) {
            e.preventDefault();
            post({ type: 'MOCKBIRD_REDO' });
            return;
          }
          if (e.key === 'Escape') {
            if (selectedEls.length) setSelection([]);
            return;
          }
          if (!selectedEls.length || mod) return;

          const step = e.shiftKey ? 10 : 1;
          let dx = 0;
          let dy = 0;
          if (e.key === 'ArrowLeft') dx = -step;
          else if (e.key === 'ArrowRight') dx = step;
          else if (e.key === 'ArrowUp') dy = -step;
          else if (e.key === 'ArrowDown') dy = step;
          else return;

          e.preventDefault();
          selectedEls.forEach(function (el) {
            if (window.getComputedStyle(el).position === 'static') {
              el.style.position = 'relative';
              el.style.left = '0px';
              el.style.top = '0px';
            }
            const left = parseFloat(el.style.left) || 0;
            const top = parseFloat(el.style.top) || 0;
            el.style.left = (left + dx) + 'px';
            el.style.top = (top + dy) + 'px';
          });
          positionOverlay();
          scheduleEmit();
        });

        // Mensagens do editor
        window.addEventListener('message', function (ev) {
          if (!ev.data) return;

          if (ev.data.type === 'MOCKBIRD_SET_MODE') {
            applyMode(ev.data.mode);
            return;
          }

          if (ev.data.type === 'MOCKBIRD_REQUEST_OUTER_HTML') {
            if (selectedEl) {
              const clone = selectedEl.cloneNode(true);
              clone.classList.remove('mb-selected', 'mb-hover', 'mb-editing');
              clone.removeAttribute('contenteditable');
              post({ type: 'MOCKBIRD_OUTER_HTML_RESPONSE', html: clone.outerHTML });
            }
            return;
          }

          if (ev.data.type === 'MOCKBIRD_DESELECT_ALL') {
            setSelection([]);
            return;
          }

          if (!selectedEls.length) return;

          if (ev.data.type === 'MOCKBIRD_UPDATE_ELEMENT') {
            const patch = ev.data.patch || {};
            selectedEls.forEach(function (el) {
              if (patch.text !== undefined && el.children.length === 0) el.innerText = patch.text;
              if (patch.bg) el.style.backgroundColor = patch.bg;
              if (patch.color) el.style.color = patch.color;
              if (patch.borderRadius) el.style.borderRadius = patch.borderRadius;
              if (patch.padding) el.style.padding = patch.padding;
            });
            positionOverlay();
            emitHtmlChanged();
          } else if (ev.data.type === 'MOCKBIRD_MOVE_UP') {
            selectedEls.slice().forEach(function (el) {
              const prev = el.previousElementSibling;
              if (prev) prev.before(el);
            });
            emitHtmlChanged();
            positionOverlay();
          } else if (ev.data.type === 'MOCKBIRD_MOVE_DOWN') {
            selectedEls.slice().reverse().forEach(function (el) {
              const next = el.nextElementSibling;
              if (next) next.after(el);
            });
            emitHtmlChanged();
            positionOverlay();
          } else if (ev.data.type === 'MOCKBIRD_DUPLICATE') {
            const clones = [];
            selectedEls.forEach(function (el) {
              const clone = el.cloneNode(true);
              clone.classList.remove('mb-selected', 'mb-hover', 'mb-editing');
              clone.removeAttribute('contenteditable');
              if (clone.hasAttribute('data-mb-id')) {
                clone.setAttribute('data-mb-id', clone.getAttribute('data-mb-id') + '-copy');
              }
              el.after(clone);
              clones.push(clone);
            });
            emitHtmlChanged();
            setSelection(clones);
          } else if (ev.data.type === 'MOCKBIRD_DELETE') {
            selectedEls.slice().forEach(function (el) { el.remove(); });
            selectedEls = [];
            selectedEl = null;
            emitHtmlChanged();
            setSelection([]);
          } else if (ev.data.type === 'MOCKBIRD_PATCH_ELEMENT') {
            const newSnippet = (ev.data.html || '').trim();
            const targetMbId = ev.data.mbId;
            const targetSel = ev.data.selector;
            let target = selectedEl;
            if (!target && targetMbId) {
              target = document.querySelector('[data-mb-id="' + targetMbId + '"]') || document.getElementById(targetMbId);
            }
            if (!target && targetSel) {
              try { target = document.querySelector(targetSel); } catch (err) {}
            }
            if (target && newSnippet) {
              const temp = document.createElement('div');
              temp.innerHTML = newSnippet;
              const newEl = temp.firstElementChild || temp;
              target.replaceWith(newEl);
              emitHtmlChanged();
              selectElement(newEl);
            }
          }
        });

        function boot() {
          ensureOverlay();
          // O canvas abre como mock navegável; o editor envia o modo real no load.
          applyMode('interactive');
        }

        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', boot);
        } else {
          boot();
        }
      </script>
      <style>
        :root { \${cssVars} }
        body:not(.mb-interactive) .mb-hover {
          outline: 1px dashed #5e6ad2 !important;
          outline-offset: 1px;
          cursor: pointer;
        }
        body:not(.mb-interactive) [contenteditable] {
          outline: none !important;
          cursor: text !important;
          user-select: text !important;
        }
        body.mb-interactive a[href],
        body.mb-interactive [data-go] {
          cursor: pointer;
        }
        body.mb-dragging, body.mb-dragging * {
          cursor: grabbing !important;
        }
        #mb-overlay {
          position: absolute;
          left: 0;
          top: 0;
          z-index: 2147483000;
          pointer-events: none;
          display: none;
        }
        #mb-overlay .mb-box {
          position: absolute;
          box-sizing: border-box;
          border: 1.5px solid #6366f1;
          box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.35), 0 0 0 4px rgba(99, 102, 241, 0.12);
          border-radius: 2px;
        }
        #mb-overlay .mb-box-primary {
          border: 2px solid #818cf8;
        }
        #mb-overlay .mb-handle {
          position: absolute;
          width: 10px;
          height: 10px;
          background: #ffffff;
          border: 2px solid #5e6ad2;
          border-radius: 3px;
          box-sizing: border-box;
          pointer-events: auto;
        }
        #mb-overlay .mb-handle[data-dir="nw"] { left: -6px; top: -6px; cursor: nwse-resize; }
        #mb-overlay .mb-handle[data-dir="n"] { left: 50%; top: -6px; margin-left: -5px; cursor: ns-resize; }
        #mb-overlay .mb-handle[data-dir="ne"] { right: -6px; top: -6px; cursor: nesw-resize; }
        #mb-overlay .mb-handle[data-dir="e"] { right: -6px; top: 50%; margin-top: -5px; cursor: ew-resize; }
        #mb-overlay .mb-handle[data-dir="se"] { right: -6px; bottom: -6px; cursor: nwse-resize; }
        #mb-overlay .mb-handle[data-dir="s"] { left: 50%; bottom: -6px; margin-left: -5px; cursor: ns-resize; }
        #mb-overlay .mb-handle[data-dir="sw"] { left: -6px; bottom: -6px; cursor: nesw-resize; }
        #mb-overlay .mb-handle[data-dir="w"] { left: -6px; top: 50%; margin-top: -5px; cursor: ew-resize; }
        #mb-drop-marker {
          position: absolute;
          z-index: 2147483000;
          background: #5e6ad2;
          border-radius: 2px;
          pointer-events: none;
          box-shadow: 0 0 0 1px rgba(94, 106, 210, 0.5);
          display: none;
        }
      </style>
`;

/**
 * Monta o documento do canvas com o runtime de seleção/edição embutido.
 */
export function buildCanvasDoc(
  html: string,
  tokens: CanvasDocTokens
): string {
  const cssVars = Object.entries(tokens)
    .map(([k, v]) => `--${k}: ${v};`)
    .join('\n');

  const runtime = CANVAS_RUNTIME.replace('${cssVars}', cssVars);

  const raw = (html || '').trim();
  const tailwindScript = '<script src="https://cdn.tailwindcss.com"></script>';

  if (raw.toLowerCase().includes('<!doctype') || raw.toLowerCase().includes('<html')) {
    if (raw.includes('</head>')) {
      return raw.replace('</head>', `${tailwindScript}${runtime}</head>`);
    } else if (raw.includes('</body>')) {
      return raw.replace('</body>', `${tailwindScript}${runtime}</body>`);
    }
    return `${raw}\n${tailwindScript}${runtime}`;
  }

  return `
      <!doctype html>
      <html lang="pt-BR">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <script src="https://cdn.tailwindcss.com"></script>
          ${runtime}
          <style>
            body {
              margin: 0;
              padding: 0;
              min-height: 100vh;
              background-color: var(--color-bg, #09090b);
              color: var(--color-text, #f4f4f5);
              font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              user-select: none;
            }
          </style>
        </head>
        <body>
          <div id="mockbird-root" style="width: 100%; min-height: 100vh;">
            ${raw || '<div class="min-h-screen flex items-center justify-center text-slate-500 font-mono text-xs">Tela vazia</div>'}
          </div>
        </body>
      </html>
    `;
}
