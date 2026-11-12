from app.jsx import html_to_jsx


def test_class_becomes_classname():
    jsx = html_to_jsx('<div class="flex gap-2">Oi</div>', "hero card")
    assert 'className="flex gap-2"' in jsx
    assert "class=" not in jsx


def test_style_becomes_object():
    jsx = html_to_jsx('<div style="background-color: red; border-radius: 8px"></div>')
    assert "style={{ backgroundColor: 'red', borderRadius: '8px' }}" in jsx


def test_void_tags_are_self_closed():
    jsx = html_to_jsx('<div><img src="a.png"><input type="text"></div>')
    assert '<img src="a.png" />' in jsx
    assert '<input type="text" />' in jsx
    assert "</img>" not in jsx


def test_inline_handlers_are_dropped():
    jsx = html_to_jsx('<button onclick="alert(1)">X</button>')
    assert "onclick" not in jsx
    assert ">X</button>" in jsx


def test_component_name_is_valid_identifier():
    jsx = html_to_jsx("<div></div>", "123 tela de login")
    assert jsx.startswith("export function Screen123TelaDeLoginScreen()")
    assert "return (" in jsx


def test_full_document_is_reduced_to_body():
    jsx = html_to_jsx("<html><head><title>x</title></head><body><p>ok</p></body></html>")
    assert "<p>ok</p>" in jsx
    assert "<html" not in jsx
    assert "<head" not in jsx
