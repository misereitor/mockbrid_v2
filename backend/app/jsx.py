"""Conversão de HTML de protótipo para JSX React.

O export anterior só trocava `class=` por `className=`, o que produzia JSX
inválido para `style="..."`, tags void, atributos reservados e entidades HTML.
"""

import html as html_lib
import re
from typing import Optional

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

ATTR_RENAMES = {
    "class": "className",
    "for": "htmlFor",
    "tabindex": "tabIndex",
    "readonly": "readOnly",
    "maxlength": "maxLength",
    "colspan": "colSpan",
    "rowspan": "rowSpan",
    "cellpadding": "cellPadding",
    "cellspacing": "cellSpacing",
    "contenteditable": "contentEditable",
    "autocomplete": "autoComplete",
    "autofocus": "autoFocus",
    "crossorigin": "crossOrigin",
    "srcset": "srcSet",
    "charset": "charSet",
    "datetime": "dateTime",
    "enctype": "encType",
    "formaction": "formAction",
    "novalidate": "noValidate",
}

_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')""",
)
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.S)


def _serialize_style(value: str) -> str:
    """`a: b; c: d` -> `{{ a: 'b', c: 'd' }}`."""
    declarations = []
    for chunk in value.split(";"):
        if ":" not in chunk:
            continue
        prop, val = chunk.split(":", 1)
        prop = prop.strip()
        val = val.strip()
        if not prop:
            continue
        camel = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), prop)
        if prop.startswith("--"):
            declarations.append(f"'{prop}': '{val}'")
        else:
            declarations.append(f"{camel}: '{val.replace(chr(39), chr(92) + chr(39))}'")
    return "{{ " + ", ".join(declarations) + " }}"


def _convert_attrs(raw: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        value = match.group(3) if match.group(3) is not None else match.group(4)
        lower = name.lower()

        if lower == "style":
            return f"style={_serialize_style(value or '')}"
        if lower.startswith("on") and len(lower) > 2:
            # on* inline não é suportado em JSX; remove para não gerar código inválido.
            return ""

        renamed = ATTR_RENAMES.get(lower, name)
        escaped = (value or "").replace('"', "&quot;")
        return f'{renamed}="{escaped}"'

    return _ATTR_RE.sub(repl, raw)


def _convert_tag(match: re.Match) -> str:
    closing, name, attrs, self_closing = match.groups()
    lower = name.lower()

    if closing:
        # JSX não aceita </br> e afins
        return "" if lower in VOID_TAGS else f"</{name}>"

    attrs_jsx = _convert_attrs(attrs or "")
    is_void = lower in VOID_TAGS or bool(self_closing)
    if is_void:
        return f"<{name}{attrs_jsx} />"
    return f"<{name}{attrs_jsx}>"


def _strip_document(html: str) -> str:
    body = re.search(r"<body[^>]*>([\s\S]*?)</body>", html, re.IGNORECASE)
    if body:
        html = body.group(1)
    else:
        html = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"</?html[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<head[\s\S]*?</head>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"</?body[^>]*>", "", html, flags=re.IGNORECASE)
    return html.strip()


def _component_name(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    candidate = "".join(w[:1].upper() + w[1:] for w in words) or "Screen"
    if candidate[0].isdigit():
        candidate = f"Screen{candidate}"
    return f"{candidate}Screen"


def html_to_jsx(html: str, component_name: Optional[str] = None) -> str:
    """Converte HTML de uma tela em um componente React funcional válido."""
    name = _component_name(component_name or "Screen")
    cleaned = _strip_document(html or "")

    # Entidades que o JSX aceita como texto puro, mas `&nbsp;` precisa virar `{" "}`
    cleaned = cleaned.replace("&nbsp;", '{"\\u00a0"}')
    cleaned = re.sub(r"<!--[\s\S]*?-->", "", cleaned)

    jsx = _TAG_RE.sub(_convert_tag, cleaned)

    return (
        f"export function {name}() {{\n"
        f"  return (\n"
        f"    <div>\n"
        f"      {jsx.strip()}\n"
        f"    </div>\n"
        f"  );\n"
        f"}}\n"
    )


def html_text_only(html: str) -> str:
    """Texto plano de um fragmento HTML (sem scripts/styles)."""
    html = re.sub(r"<(script|style)[\s\S]*?</\1>", "", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()
