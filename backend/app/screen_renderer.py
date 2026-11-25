"""Motor de Renderização Headless e Simulação de Interações para Agentes MCP.

Permite que agentes externos (Claude Code, Cursor, Windsurf) renderizem screenshots
de alta fidelidade, executem sequências de ações interativas no Mockbird, diagnostiquem
erros de scripts/listeners e validem a integridade das telas contra regras de design.
"""

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Page, Route

from app.config import settings

VIEWPORT_CONFIGS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}

PLACEHOLDER_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">'
    b'<rect width="120" height="120" fill="#f1f5f9" rx="8"/>'
    b'<path d="M40 75l12-16 10 12 14-18 16 22H28z" fill="#94a3b8"/>'
    b'<circle cx="46" cy="44" r="6" fill="#94a3b8"/>'
    b'</svg>'
)


def _resolve_local_asset_bytes(url: str) -> Optional[tuple[bytes, str]]:
    """Tenta localizar um asset local em disco pelo caminho ou ID da URL."""
    try:
        root = Path(settings.ASSETS_DIR)
        if not root.exists():
            return None

        # Procura arquivos correspondentes ao sufixo da URL
        parts = url.rstrip("/").split("/")
        candidate_name = parts[-1]
        for p in root.rglob(candidate_name):
            if p.is_file():
                ext = p.suffix.lower()
                ctype = "image/png"
                if ext in [".jpg", ".jpeg"]:
                    ctype = "image/jpeg"
                elif ext == ".svg":
                    ctype = "image/svg+xml"
                elif ext == ".webp":
                    ctype = "image/webp"
                elif ext == ".gif":
                    ctype = "image/gif"
                return p.read_bytes(), ctype
    except Exception:
        pass
    return None


async def _setup_page_network_and_diagnostics(
    page: Page,
    console_logs: List[Dict[str, Any]],
    page_errors: List[str],
) -> None:
    """Configura interceptação resiliente de rotas (evitando timeouts de 30s) e monitoramento de logs."""
    page.set_default_timeout(10000)
    page.set_default_navigation_timeout(10000)

    page.on("console", lambda msg: console_logs.append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    async def route_handler(route: Route) -> None:
        url = route.request.url
        # Intercepta assets do Mockbird (/api/assets/...)
        if "/api/assets/" in url or url.startswith("/api/assets/"):
            found = _resolve_local_asset_bytes(url)
            if found:
                data, ctype = found
                await route.fulfill(status=200, body=data, content_type=ctype)
                return
            # Se não encontrado localmente, responde placeholder SVG rápido para não dar timeout
            await route.fulfill(status=200, body=PLACEHOLDER_SVG, content_type="image/svg+xml")
            return

        # URLs data: ou Tailwind CDN ou fontes
        if url.startswith("data:"):
            await route.continue_()
            return

        if any(h in url for h in ["cdn.tailwindcss.com", "fonts.googleapis.com", "fonts.gstatic.com"]):
            try:
                await route.continue_()
            except Exception:
                await route.fulfill(status=200, body=b"", content_type="text/javascript")
            return

        # Para imagens ou mídias externas desconhecidas que possam travar sem rede externa
        if route.request.resource_type in ["image", "media", "font"]:
            try:
                await route.continue_()
            except Exception:
                await route.fulfill(status=200, body=PLACEHOLDER_SVG, content_type="image/svg+xml")
            return

        try:
            await route.continue_()
        except Exception:
            await route.abort()

    await page.route("**/*", route_handler)


def build_full_page_html(
    html_content: str,
    css_content: str = "",
    js_content: str = "",
    tokens: Optional[Dict[str, Any]] = None,
    theme: str = "light",
) -> str:
    """Monta documento HTML autocontido com Tailwind CDN, CSS, tokens e script."""
    tokens = tokens or {}
    light_tokens = tokens.get("light") or {}
    dark_tokens = tokens.get("dark") or {}
    shared_tokens = tokens.get("shared") or {}

    active_tokens = dict(shared_tokens)
    if theme == "dark":
        active_tokens.update(dark_tokens)
    else:
        active_tokens.update(light_tokens)

    # Injeta variáveis CSS de design tokens
    css_rules = " ".join(f"--{k}: {v};" for k, v in active_tokens.items() if v)
    token_style = f":root, [data-theme='{theme}'], html, body {{ {css_rules} }}"

    raw_html = (html_content or "").strip()
    is_full_doc = "<html" in raw_html.lower() or "<!doctype" in raw_html.lower()

    navigation_script = """
    // Suporte a mock navigation e captura de eventos
    window.__mockbird_actions = [];
    document.addEventListener('click', function(e) {
      var target = e.target.closest('[data-mb-nav]');
      if (target) {
        var dest = target.getAttribute('data-mb-nav');
        window.__mockbird_last_navigation = dest;
        window.__mockbird_navigated = true;
      }
      var actionTarget = e.target.closest('[data-action], [data-mb-action], button, a');
      if (actionTarget) {
        window.__mockbird_actions.push({
          type: 'click',
          tag: actionTarget.tagName.toLowerCase(),
          id: actionTarget.id || null,
          action: actionTarget.getAttribute('data-action') || actionTarget.getAttribute('data-mb-action') || null
        });
      }
    }, true);
    """

    custom_styles = f"""
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
      {token_style}
      body {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
        background-color: var(--color-bg, {('#090d16' if theme == 'dark' else '#ffffff')});
        color: var(--color-text, {('#f8fafc' if theme == 'dark' else '#0f172a')});
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      }}
      {css_content or ''}
    </style>
    """

    custom_scripts = f"""
    <script>
      {navigation_script}
      {js_content or ''}
    </script>
    """

    if is_full_doc:
        # Injeta estilos no <head> e scripts antes de </body> preservando a integridade
        doc = raw_html
        if "<head>" in doc:
            doc = doc.replace("<head>", f"<head>{custom_styles}", 1)
        elif "<head " in doc:
            doc = re.sub(r"(<head[^>]*>)", r"\1" + custom_styles, doc, count=1, flags=re.IGNORECASE)
        else:
            doc = f"{custom_styles}\n{doc}"

        if "</body>" in doc:
            doc = doc.replace("</body>", f"{custom_scripts}</body>", 1)
        else:
            doc = f"{doc}\n{custom_scripts}"

        # Assegura atributo data-theme e classe
        doc = re.sub(r"<html\b([^>]*)>", rf'<html\1 data-theme="{theme}" class="{theme}">', doc, count=1, flags=re.IGNORECASE)
        return doc

    # Fragmento HTML: envelopa em documento padrão
    document = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="{theme}" class="{theme}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  {custom_styles}
</head>
<body data-theme="{theme}">
  {raw_html}
  {custom_scripts}
</body>
</html>"""
    return document


async def render_screen_screenshot(
    html_content: str,
    css_content: str = "",
    js_content: str = "",
    tokens: Optional[Dict[str, Any]] = None,
    viewport_name: str = "desktop",
    theme: str = "light",
    custom_width: Optional[int] = None,
    custom_height: Optional[int] = None,
    full_page: bool = False,
) -> Dict[str, Any]:
    """Renderiza a tela em navegador Chromium headless e extrai screenshot PNG em base64 com resiliência de rede."""
    vp = VIEWPORT_CONFIGS.get(viewport_name.lower(), VIEWPORT_CONFIGS["desktop"])
    width = custom_width or vp["width"]
    height = custom_height or vp["height"]

    full_html = build_full_page_html(
        html_content=html_content,
        css_content=css_content,
        js_content=js_content,
        tokens=tokens,
        theme=theme,
    )

    console_logs: List[Dict[str, Any]] = []
    page_errors: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2,  # Retina crisp
        )
        page = await context.new_page()
        await _setup_page_network_and_diagnostics(page, console_logs, page_errors)

        try:
            await page.set_content(full_html, wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass  # Continua mesmo se algum subrecurso demorar

        await page.wait_for_timeout(250)

        screenshot_bytes = await page.screenshot(
            type="png",
            full_page=full_page,
        )
        await browser.close()

    b64_image = base64.b64encode(screenshot_bytes).decode("ascii")

    return {
        "screenshot_bytes": screenshot_bytes,
        "image_base64": b64_image,
        "image_data_uri": f"data:image/png;base64,{b64_image}",
        "width": width,
        "height": height,
        "viewport": viewport_name,
        "theme": theme,
        "size_bytes": len(screenshot_bytes),
        "console_logs": console_logs[-10:],
        "page_errors": page_errors,
    }


async def simulate_element_interaction(
    html_content: str,
    css_content: str = "",
    js_content: str = "",
    tokens: Optional[Dict[str, Any]] = None,
    element_mb_id: Optional[str] = None,
    selector: Optional[str] = None,
    action: str = "click",
    input_value: Optional[str] = None,
    viewport_name: str = "desktop",
    theme: str = "light",
    capture_screenshot: bool = True,
) -> Dict[str, Any]:
    """Executa interação em um elemento da tela, analisando efeitos no DOM e capturando logs e erros de script."""
    target_selector = selector
    if element_mb_id:
        clean_id = element_mb_id.lstrip("#").strip()
        target_selector = f"[data-mb-id='{clean_id}'], #{clean_id}"

    if not target_selector:
        raise ValueError("Informe 'element_mb_id' ou 'selector' para interagir com o elemento.")

    vp = VIEWPORT_CONFIGS.get(viewport_name.lower(), VIEWPORT_CONFIGS["desktop"])
    width = vp["width"]
    height = vp["height"]

    full_html = build_full_page_html(
        html_content=html_content,
        css_content=css_content,
        js_content=js_content,
        tokens=tokens,
        theme=theme,
    )

    console_logs: List[Dict[str, Any]] = []
    page_errors: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
        )
        page = await context.new_page()
        await _setup_page_network_and_diagnostics(page, console_logs, page_errors)

        try:
            await page.set_content(full_html, wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass

        await page.wait_for_timeout(200)

        locator = page.locator(target_selector).first
        count = await locator.count()
        if count == 0:
            await browser.close()
            raise ValueError(f"Elemento não encontrado na tela com o seletor: '{target_selector}'")

        tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
        initial_text = (await locator.inner_text()) or ""
        initial_classes = (await locator.get_attribute("class")) or ""
        nav_dest = await locator.get_attribute("data-mb-nav")
        href_attr = await locator.get_attribute("href")
        onclick_attr = await locator.get_attribute("onclick")
        data_action = await locator.get_attribute("data-action")

        # Snapshot de classes antes da ação para detectar mutações em contêineres/pais
        parent_snapshot_before = await locator.evaluate("""
            el => {
                let curr = el.parentElement;
                const parents = [];
                while (curr && curr !== document.body && parents.length < 5) {
                    parents.push({ tag: curr.tagName.toLowerCase(), id: curr.id, cls: curr.className });
                    curr = curr.parentElement;
                }
                return parents;
            }
        """)

        # 2. Executa a ação
        action_name = action.lower()
        if action_name == "click":
            await locator.click()
        elif action_name == "input":
            await locator.fill(input_value or "")
        elif action_name == "hover":
            await locator.hover()
        else:
            await locator.click()

        # Aguarda listeners, mutações de DOM ou transições
        await page.wait_for_timeout(350)

        # 3. Inspeciona alterações pós-interação
        post_classes = (await locator.get_attribute("class")) or ""
        post_text = (await locator.inner_text()) or ""
        last_nav = await page.evaluate("() => window.__mockbird_last_navigation || null")
        body_classes = await page.evaluate("() => document.body.className")

        parent_snapshot_after = await locator.evaluate("""
            el => {
                let curr = el.parentElement;
                const parents = [];
                while (curr && curr !== document.body && parents.length < 5) {
                    parents.push({ tag: curr.tagName.toLowerCase(), id: curr.id, cls: curr.className });
                    curr = curr.parentElement;
                }
                return parents;
            }
        """)

        # Detecta mutações em nós pais ou irmãos
        parent_mutations = []
        for b, a in zip(parent_snapshot_before, parent_snapshot_after):
            if b["cls"] != a["cls"]:
                parent_mutations.append({
                    "tag": a["tag"],
                    "id": a["id"],
                    "before": b["cls"],
                    "after": a["cls"],
                })

        shot_bytes = None
        screenshot_b64 = None
        if capture_screenshot:
            shot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(shot_bytes).decode("ascii")

        await browser.close()

    classes_added = list(set(post_classes.split()) - set(initial_classes.split()))
    classes_removed = list(set(initial_classes.split()) - set(post_classes.split()))

    return {
        "status": "success",
        "action": action_name,
        "target": {
            "selector_used": target_selector,
            "tag": tag_name,
            "initial_text": initial_text.strip(),
            "has_onclick": bool(onclick_attr),
            "data_action": data_action,
            "nav_destination": nav_dest or last_nav or href_attr,
        },
        "dom_effects": {
            "text_changed": post_text.strip() != initial_text.strip(),
            "new_text": post_text.strip() if post_text.strip() != initial_text.strip() else None,
            "classes_added": classes_added,
            "classes_removed": classes_removed,
            "parent_mutations": parent_mutations,
            "body_classes": body_classes,
            "navigation_triggered": bool(nav_dest or last_nav),
            "navigation_target": nav_dest or last_nav,
        },
        "diagnostics": {
            "console_logs": console_logs,
            "page_errors": page_errors,
            "has_script_error": len(page_errors) > 0,
        },
        "screenshot_bytes": shot_bytes,
        "screenshot_base64": screenshot_b64,
        "viewport": viewport_name,
        "theme": theme,
    }


async def simulate_sequence_interactions(
    html_content: str,
    actions: List[Dict[str, Any]],
    css_content: str = "",
    js_content: str = "",
    tokens: Optional[Dict[str, Any]] = None,
    viewport_name: str = "desktop",
    theme: str = "light",
    full_page: bool = False,
) -> Dict[str, Any]:
    """Executa uma sequência de passos (clicar, aguardar, digitar) e extrai o screenshot do estado final resultante."""
    vp = VIEWPORT_CONFIGS.get(viewport_name.lower(), VIEWPORT_CONFIGS["desktop"])
    width = vp["width"]
    height = vp["height"]

    full_html = build_full_page_html(
        html_content=html_content,
        css_content=css_content,
        js_content=js_content,
        tokens=tokens,
        theme=theme,
    )

    console_logs: List[Dict[str, Any]] = []
    page_errors: List[str] = []
    action_results: List[Dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
        )
        page = await context.new_page()
        await _setup_page_network_and_diagnostics(page, console_logs, page_errors)

        try:
            await page.set_content(full_html, wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass

        await page.wait_for_timeout(250)

        for idx, act in enumerate(actions):
            act_type = str(act.get("action") or "click").lower()
            selector = act.get("selector") or (f"[data-mb-id='{act.get('element_mb_id')}']" if act.get("element_mb_id") else None)

            step_res = {"step": idx + 1, "action": act_type, "status": "executed"}
            try:
                if act_type == "wait":
                    ms = int(act.get("ms") or 500)
                    await page.wait_for_timeout(ms)
                    step_res["details"] = f"Aguardou {ms}ms"
                elif act_type == "click":
                    if not selector:
                        raise ValueError("Ação 'click' exige 'selector' ou 'element_mb_id'")
                    await page.locator(selector).first.click()
                    await page.wait_for_timeout(200)
                    step_res["details"] = f"Clicou em {selector}"
                elif act_type in ["input", "fill", "type"]:
                    if not selector:
                        raise ValueError(f"Ação '{act_type}' exige 'selector' ou 'element_mb_id'")
                    val = str(act.get("value") or act.get("text") or "")
                    await page.locator(selector).first.fill(val)
                    step_res["details"] = f"Preencheu '{val}' em {selector}"
                elif act_type == "hover":
                    if not selector:
                        raise ValueError("Ação 'hover' exige 'selector' ou 'element_mb_id'")
                    await page.locator(selector).first.hover()
                    step_res["details"] = f"Hover sobre {selector}"
                else:
                    step_res["status"] = "skipped"
                    step_res["details"] = f"Ação desconhecida: {act_type}"
            except Exception as e:
                step_res["status"] = "failed"
                step_res["error"] = str(e)
                action_results.append(step_res)
                break

            action_results.append(step_res)

        screenshot_bytes = await page.screenshot(type="png", full_page=full_page)
        await browser.close()

    b64_image = base64.b64encode(screenshot_bytes).decode("ascii")

    return {
        "status": "success",
        "actions_executed": action_results,
        "screenshot_bytes": screenshot_bytes,
        "image_base64": b64_image,
        "image_data_uri": f"data:image/png;base64,{b64_image}",
        "viewport": viewport_name,
        "theme": theme,
        "diagnostics": {
            "console_logs": console_logs,
            "page_errors": page_errors,
        },
    }


async def diagnose_screen_structure(
    html_content: str,
    css_content: str = "",
    js_content: str = "",
    tokens: Optional[Dict[str, Any]] = None,
    viewport_name: str = "desktop",
    theme: str = "light",
) -> Dict[str, Any]:
    """Inspeciona a tela, listando scripts, ordem de carga, elementos interativos e erros de console."""
    vp = VIEWPORT_CONFIGS.get(viewport_name.lower(), VIEWPORT_CONFIGS["desktop"])
    width = vp["width"]
    height = vp["height"]

    full_html = build_full_page_html(
        html_content=html_content,
        css_content=css_content,
        js_content=js_content,
        tokens=tokens,
        theme=theme,
    )

    console_logs: List[Dict[str, Any]] = []
    page_errors: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
        )
        page = await context.new_page()
        await _setup_page_network_and_diagnostics(page, console_logs, page_errors)

        try:
            await page.set_content(full_html, wait_until="domcontentloaded", timeout=10000)
        except Exception as e:
            page_errors.append(f"Timeout ou erro no carregamento do DOM: {str(e)}")

        await page.wait_for_timeout(300)

        # Inspeciona elementos interativos
        interactive_elements = await page.evaluate("""
            () => {
                const list = [];
                const nodes = document.querySelectorAll('button, a, input, select, textarea, [data-mb-nav], [data-action], [data-mb-action], [onclick], [role="button"]');
                nodes.forEach((el, idx) => {
                    if (idx < 50) {
                        list.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id || null,
                            text: (el.innerText || el.value || '').trim().slice(0, 50),
                            classes: el.className || null,
                            nav: el.getAttribute('data-mb-nav') || null,
                            action: el.getAttribute('data-action') || el.getAttribute('data-mb-action') || null,
                            has_onclick: !!el.getAttribute('onclick'),
                            visible: el.offsetParent !== null
                        });
                    }
                });
                return list;
            }
        """)

        script_tags = await page.evaluate("""
            () => {
                const scripts = [];
                document.querySelectorAll('script').forEach(s => {
                    scripts.push({
                        src: s.src || null,
                        inline: !s.src,
                        length: s.innerText ? s.innerText.length : 0
                    });
                });
                return scripts;
            }
        """)

        await browser.close()

    return {
        "status": "success",
        "viewport": viewport_name,
        "theme": theme,
        "diagnostics": {
            "page_errors": page_errors,
            "console_logs": console_logs,
            "has_runtime_errors": len(page_errors) > 0,
        },
        "scripts": {
            "total_scripts": len(script_tags),
            "script_list": script_tags,
            "has_js_content": bool(js_content and js_content.strip()),
        },
        "interactive_elements": {
            "count": len(interactive_elements),
            "elements": interactive_elements,
        },
    }


def audit_screen_rules(
    html_content: str,
    css_content: str = "",
    js_content: str = "",
) -> Dict[str, Any]:
    """Aplica regras de validação estruturais (equivalente a validate.mjs) na tela publicada."""
    html = html_content or ""
    css = css_content or ""
    _ = js_content

    issues: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}

    # 1. Checagem de Dark Mode
    has_dark_classes = bool(re.search(r"\bdark:[a-z0-9_-]+", html))
    has_theme_vars = "--color-" in html or "--color-" in css
    dark_mode_supported = has_dark_classes or has_theme_vars
    checks["dark_mode"] = {
        "status": "pass" if dark_mode_supported else "warn",
        "has_dark_classes": has_dark_classes,
        "has_theme_vars": has_theme_vars,
        "message": "Suporte a tema escuro detectado" if dark_mode_supported else "Nenhuma classe 'dark:' ou variável CSS de tema encontrada.",
    }
    if not dark_mode_supported:
        issues.append({
            "rule": "dark_mode",
            "severity": "warn",
            "message": "A tela não parece conter variantes para Dark Mode (classes 'dark:*' ou tokens CSS)."
        })

    # 2. Checagem de Responsividade / Variantes
    responsive_classes = bool(re.search(r"\b(sm|md|lg|xl|2xl):[a-z0-9_-]+", html))
    has_media_queries = "@media" in css
    responsive_supported = responsive_classes or has_media_queries
    checks["responsiveness"] = {
        "status": "pass" if responsive_supported else "info",
        "has_responsive_classes": responsive_classes,
        "has_media_queries": has_media_queries,
        "message": "Classes responsivas detectadas" if responsive_supported else "Tela com layout fixo ou sem breakpoints responsivos declarados.",
    }

    # 3. Interação Mínima
    has_nav = "data-mb-nav" in html
    has_buttons = "<button" in html.lower() or "role=\"button\"" in html.lower()
    has_inputs = "<input" in html.lower() or "<select" in html.lower()
    has_actions = "data-action" in html or "onclick=" in html
    checks["interactivity"] = {
        "status": "pass" if (has_nav or has_buttons or has_inputs or has_actions) else "info",
        "has_mock_navigation": has_nav,
        "has_buttons": has_buttons,
        "has_inputs": has_inputs,
        "has_actions": has_actions,
    }

    # 4. Integridade Estrutural
    unclosed_tags = []
    for tag in ["div", "section", "main", "nav", "article", "header", "footer"]:
        opens = len(re.findall(rf"<{tag}\b", html, re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}>", html, re.IGNORECASE))
        if opens != closes:
            unclosed_tags.append({"tag": tag, "opened": opens, "closed": closes})

    if unclosed_tags:
        issues.append({
            "rule": "structural_integrity",
            "severity": "warn",
            "message": f"Divergência no fechamento de tags: {unclosed_tags}"
        })
        checks["structural_integrity"] = {"status": "warn", "discrepancies": unclosed_tags}
    else:
        checks["structural_integrity"] = {"status": "pass", "message": "Tags principais balanceadas"}

    overall_status = "pass"
    if any(i["severity"] == "error" for i in issues):
        overall_status = "fail"
    elif any(i["severity"] == "warn" for i in issues):
        overall_status = "warn"

    return {
        "overall_status": overall_status,
        "total_issues": len(issues),
        "issues": issues,
        "checks": checks,
    }
