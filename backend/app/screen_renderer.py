"""Motor de Renderização Headless e Simulação de Interações para Agentes MCP.

Permite que agentes externos (Claude Code, Cursor, Windsurf) renderizem screenshots
de alta fidelidade e executem cliques/ações interativas no Mockbird, comprovando
remotamente a equivalência visual e funcional das telas.
"""

import base64
from typing import Any, Dict, Optional
from playwright.async_api import async_playwright

VIEWPORT_CONFIGS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}


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

    # Tailwind e resets básicos
    document = f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="{theme}" class="{theme}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
</head>
<body data-theme="{theme}">
  {html_content or ''}
  <script>
    // Suporte a mock navigation
    document.addEventListener('click', function(e) {{
      var target = e.target.closest('[data-mb-nav]');
      if (target) {{
        var dest = target.getAttribute('data-mb-nav');
        window.__mockbird_last_navigation = dest;
        window.__mockbird_navigated = true;
      }}
    }});
    {js_content or ''}
  </script>
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
    """Renderiza a tela em navegador Chromium headless e extrai screenshot PNG em base64."""
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2,  # Retina crisp screenshot
        )
        page = await context.new_page()

        await page.set_content(full_html, wait_until="load")
        # Pequeno delay para Tailwind CDN e animações CSS estabilizarem
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
    """Executa interação (clique, input, hover) em um elemento da tela e analisa os efeitos colaterais."""
    # Monta seletor de busca
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

        await page.set_content(full_html, wait_until="load")
        await page.wait_for_timeout(200)

        # 1. Inspeciona o elemento alvo antes da interação
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

        # Aguarda 300ms para listeners, mutações de DOM ou transições
        await page.wait_for_timeout(300)

        # 3. Inspeciona alterações pós-interação
        post_classes = (await locator.get_attribute("class")) or ""
        post_text = (await locator.inner_text()) or ""
        last_nav = await page.evaluate("() => window.__mockbird_last_navigation || null")
        body_classes = await page.evaluate("() => document.body.className")

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
            "nav_destination": nav_dest or last_nav or href_attr,
        },
        "dom_effects": {
            "text_changed": post_text.strip() != initial_text.strip(),
            "new_text": post_text.strip() if post_text.strip() != initial_text.strip() else None,
            "classes_added": classes_added,
            "classes_removed": classes_removed,
            "body_classes": body_classes,
            "navigation_triggered": bool(nav_dest or last_nav),
            "navigation_target": nav_dest or last_nav,
        },
        "screenshot_bytes": shot_bytes,
        "screenshot_base64": screenshot_b64,
        "viewport": viewport_name,
        "theme": theme,
    }
