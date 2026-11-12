from app.agent.graph import balance_html_tags, heal_and_wrap_html, clean_extracted_html


def test_fragment_is_wrapped_in_full_document():
    out = heal_and_wrap_html('<div data-mb-id="x"><h1>Oi</h1></div>')
    assert out.startswith("<!DOCTYPE html>")
    assert "__BODY_CONTENT__" not in out
    assert '<div data-mb-id="x">' in out
    assert "tailwindcss.com" in out


def test_unclosed_tags_are_balanced():
    out = balance_html_tags("<div><section><p>texto")
    assert out.endswith("</p></section></div>")


def test_unfinished_style_block_is_discarded():
    out = heal_and_wrap_html("<div>ok</div><style>.a { color: red;")
    # O CSS inacabado do modelo é descartado (o template padrão tem seu próprio <style>).
    assert "color: red" not in out
    # O conteúdo é preservado; `data-mb-id` é injetado automaticamente.
    assert ">ok</div>" in out


def test_extracts_fenced_code_and_heals():
    text = "Aqui está:\n```html\n<div><span>a</span></div>\n```\nPronto."
    out = clean_extracted_html(text)
    assert "<span>a</span>" in out
    assert "Aqui está" not in out
