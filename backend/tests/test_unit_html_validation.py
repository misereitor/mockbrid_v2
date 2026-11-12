"""Testes do validador/reparador de HTML gerado por LLM."""

import re

from app.agent.htmlkit import (
    assemble_sections,
    extract_html,
    sanitize_html,
    validate_and_repair,
    validate_section,
)


VALID_SECTION = (
    '<section data-mb-id="hero" class="min-h-screen flex items-center bg-[#09090b] p-16">'
    '<h1 data-mb-id="hero-title" class="text-6xl font-extrabold text-white">Construa mais rápido</h1>'
    '<p data-mb-id="hero-copy" class="text-slate-300 text-lg">Plataforma completa para times de produto.</p>'
    '<button data-mb-id="hero-cta" class="bg-white text-black px-6 py-3 rounded-xl">Começar agora</button>'
    "</section>"
)


def test_extract_prefers_html_block_over_prose():
    text = "Vou criar a tela.\n\n```html\n<div class='p-4'><h1>Oi</h1></div>\n```\n\nEspero que goste!"
    assert extract_html(text).startswith("<div")
    assert extract_html(text).endswith("</div>")


def test_extract_chooses_largest_block_and_skips_small_examples():
    text = (
        "Exemplo curto:\n```html\n<div>x</div>\n```\n"
        "Agora a tela:\n```html\n" + VALID_SECTION + "\n```\n"
    )
    assert "hero-title" in extract_html(text)


def test_extract_handles_unterminated_fence():
    text = "```html\n<section class='p-4'><h1>Título</h1>"
    extracted = extract_html(text)
    assert "<section" in extracted and "Título" in extracted


def test_extract_ignores_thinking_blocks():
    text = "<thinking>O usuário quer um hero.</thinking>\n```html\n<div class='p-2'>Ok</div>\n```"
    assert "usuário" not in extract_html(text)
    assert "<div" in extract_html(text)


def test_sanitize_removes_scripts_handlers_and_javascript_urls():
    dirty = (
        '<div onclick="alert(1)" class="p-2">'
        '<script>steal()</script><img src="javascript:alert(1)">'
        '<a href="https://ok.test" onmouseover="x()">link</a></div>'
    )
    clean = sanitize_html(dirty)
    assert "<script" not in clean
    assert "onclick" not in clean and "onmouseover" not in clean
    assert "javascript:" not in clean


def test_truncated_document_is_repaired_and_wrapped():
    raw = (
        '<div id="app-root" class="p-8"><h1 class="text-4xl">Dashboard</h1>'
        '<section class="grid"><div class="card p-4">Receita</div>'
    )
    report = validate_and_repair(raw, mode="full")
    assert report.ok, report.errors
    assert report.html.count("<html") == 1
    assert "cdn.tailwindcss.com" in report.html
    assert report.html.rstrip().endswith("</html>")
    assert any("Tags fechadas" in w for w in report.warnings)


def test_stray_closing_tag_is_removed():
    raw = "<div class='p-4'><h1>Oi</h1></div></div>"
    report = validate_and_repair(raw, mode="full")
    assert "Fechamento </div> sem abertura" in " ".join(report.errors)
    assert report.html.count("</div>") == 1


def test_full_document_head_is_stripped_and_reenveloped():
    raw = (
        "<!DOCTYPE html><html><head><title>x</title><style>.a{color:red}</style></head>"
        "<body><div id='app-root' class='p-6'><h1>Tela</h1><p class='text-slate-300'>Conteúdo real</p></div></body></html>"
    )
    report = validate_and_repair(raw, mode="full")
    assert report.ok, report.errors
    assert report.html.count("<head>") == 1
    assert "<title>x</title>" not in report.html


def test_missing_mb_ids_are_injected_and_duplicates_renamed():
    raw = (
        "<div class='p-4'><h1>Painel de vendas do trimestre</h1>"
        "<button data-mb-id='btn'>Exportar relatório</button>"
        "<button data-mb-id='btn'>Compartilhar painel</button></div>"
    )
    report = validate_and_repair(raw, mode="full")
    assert report.ok, report.errors
    assert report.html.count('data-mb-id="btn"') == 1
    assert re.search(r'data-mb-id="btn-\d+"', report.html), "id duplicado precisa ser renomeado"
    assert report.html.count("data-mb-id=") >= 4
    assert any("inserido" in w for w in report.warnings)


def test_lazy_placeholder_is_rejected():
    raw = (
        "<div class='p-4'><h1>Landing</h1><!-- insira o hero aqui -->"
        "<p class='text-slate-300'>Lorem ipsum dolor sit amet consectetur.</p></div>"
    )
    report = validate_and_repair(raw, mode="full")
    assert not report.ok
    assert any("placeholder" in e or "Resumo" in e for e in report.errors)


def test_tiny_html_is_rejected():
    report = validate_and_repair("<div class='p-1'>ok</div>", mode="full")
    assert not report.ok
    assert any("curto" in e for e in report.errors)


def test_element_patch_keeps_target_mb_id_and_single_root():
    raw = "<button class='bg-emerald-500 text-white px-4 py-2 rounded'>Garantir vaga</button>"
    report = validate_and_repair(raw, mode="element", mb_id="btn-cta")
    assert report.ok, report.errors
    assert report.html.startswith("<button")
    assert 'data-mb-id="btn-cta"' in report.html
    assert "<html" not in report.html


def test_element_patch_with_two_roots_is_flagged():
    raw = "<button data-mb-id='a'>A</button><div data-mb-id='b'>B</div>"
    report = validate_and_repair(raw, mode="element", mb_id="a")
    assert not report.ok
    assert any("único elemento" in e for e in report.errors)


def test_element_patch_from_full_document_uses_only_body_element():
    raw = "<html><body><span data-mb-id='x' class='text-sm'>Olá</span></body></html>"
    report = validate_and_repair(raw, mode="element", mb_id="x")
    assert report.ok, report.errors
    assert report.html.startswith("<span")


def test_validate_section_detects_empty_and_placeholder():
    assert not validate_section("").ok
    assert not validate_section("<section class='p-2'></section>").ok
    assert validate_section(VALID_SECTION).ok


def test_assemble_sections_builds_single_document():
    second = (
        '<section data-mb-id="features" class="py-24 px-8"><h2 class="text-4xl text-white">Recursos</h2>'
        '<p class="text-slate-300">Tudo o que você precisa em um só lugar.</p></section>'
    )
    report = assemble_sections([VALID_SECTION, second])
    assert report.ok, report.errors
    assert report.html.count("<html") == 1
    assert 'id="app-root"' in report.html
    assert "hero-title" in report.html and "features" in report.html


def test_repair_prompt_lists_problems():
    report = validate_and_repair("<div class='p-1'>ok</div>", mode="full")
    prompt = report.repair_prompt()
    assert "rejeitado pelo validador" in prompt
    assert "curto" in prompt
