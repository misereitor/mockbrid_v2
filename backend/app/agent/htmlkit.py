"""Extração, validação e reparo de HTML gerado por LLM.

O modelo devolve texto livre: às vezes um bloco ```html```, às vezes prosa antes
e depois, às vezes truncado no meio de uma tag, às vezes o documento inteiro
quando pedimos só um fragmento. Antes deste módulo, cada rota tinha sua própria
regex e o resultado ia direto para o canvas — daí as telas quebradas.

Fluxo aplicado a todo patch:

    extract_html -> sanitize -> rebuild/balance -> ensure_mb_ids -> wrap -> validate

`validate_and_repair` devolve sempre um `PatchValidation` com o HTML reparado,
erros estruturais, avisos e uma nota. Quem chama decide se aplica ou pede
reparo ao modelo (`errors` vira prompt de correção).
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, List, Optional

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

# Tags removidas por segurança/estabilidade (o canvas é sandboxed, mas o mesmo
# HTML também é servido em apresentações públicas).
DANGEROUS_TAGS = ("script", "iframe", "object", "embed", "base", "frame", "frameset")

# Elementos que precisam de data-mb-id para serem editáveis no canvas.
ID_TARGET_TAGS = {
    "div", "section", "header", "footer", "nav", "main", "article", "aside",
    "button", "a", "img", "input", "textarea", "select", "form", "h1", "h2",
    "h3", "h4", "p", "li", "ul", "ol", "table", "dialog",
}

# Padrões de pseudo-código independentes do domínio/projeto. Não coloque aqui
# nomes de seções de uma demo específica: a auditoria deve funcionar para
# qualquer tela gerada.
LAZY_PATTERNS = [
    r"<!--\s*(?:insira|adicione|coloque aqui|todo|restante|código continua)\s*-->",
    r"\[\s*(?:insira|coloque|todo|placeholder|seu texto|seu título)\s*\]",
    r"\b(?:lorem\s+ipsum|texto\s+de\s+exemplo|sample\s+text)\b",
    r"(?:TODO|FIXME|IMPLEMENT(?:AR|ATION)?)\s*[:\-]",
    r"\.\.\.\s*(?:resto|demais|outros|continua|more|remaining)",
    r"\b(?:coming\s+soon|em\s+breve)\b",
]
LAZY_OUTLINE_PATTERNS = LAZY_PATTERNS  # compatibilidade com importadores antigos
_LAZY_RE = [re.compile(p, re.IGNORECASE) for p in LAZY_PATTERNS]


def find_lazy_markers(html: str) -> List[str]:
    """Retorna os padrões de pseudo-código encontrados no HTML."""
    return [pattern.pattern for pattern in _LAZY_RE if pattern.search(html or "")]

QUALITY_SCORE_MIN = 70

HTML_CANVAS_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mockbird Interface</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=Bebas+Neue&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    .font-display { font-family: 'Bebas Neue', sans-serif; }
    .font-mono-accent { font-family: 'Space Grotesk', sans-serif; }
  </style>
</head>
<body class="bg-[#09090b] text-slate-100 antialiased min-h-screen">
__BODY_CONTENT__
</body>
</html>"""


@dataclass
class PatchValidation:
    ok: bool
    html: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: int = 100
    metrics: dict = field(default_factory=dict)

    def to_event(self) -> dict:
        return {
            "ok": self.ok,
            "score": self.score,
            "errors": self.errors,
            "warnings": self.warnings,
            "chars": len(self.html or ""),
        }

    def repair_prompt(self) -> str:
        """Instrução curta com os defeitos detectados, para pedir correção ao modelo."""
        problems = "\n".join(f"- {e}" for e in (self.errors + self.warnings)) or "- Estrutura incompleta."
        return (
            "O HTML anterior foi rejeitado pelo validador do Mockbird com os seguintes problemas:\n"
            f"{problems}\n"
            "Corrija esses problemas e devolva o HTML COMPLETO e fechado dentro de ```html ... ```. "
            "Não resuma, não use placeholders e não escreva comentários de TODO."
        )


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```[ \t]*([a-zA-Z0-9_-]*)[ \t]*\r?\n?([\s\S]*?)(?:```|$)")
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>[\s\S]*?</\1>", re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<(think|thinking|reasoning)>[\s\S]*$", re.IGNORECASE)


def _html_density(text: str) -> int:
    """Quanto um trecho 'parece' HTML: tags abertas + tags fechadas."""
    return len(re.findall(r"</?[a-zA-Z][a-zA-Z0-9:-]*(?:\s[^<>]*)?>", text or ""))


def _has_markup(text: str) -> bool:
    return bool(text) and "<" in text and ">" in text and _html_density(text) >= 1


def extract_html(text: str) -> str:
    """Extrai o melhor bloco HTML de uma resposta de LLM.

    Regras:
    1. Remove blocos de raciocínio (`` thinking``/``<thinking>``).
    2. Entre blocos de código fechados, escolhe o com mais marcação HTML.
    3. Sem bloco fechado, usa o último bloco iniciado (truncamento comum).
    4. Sem cerca, corta do primeiro documento/elemento até o fim.
    """
    if not text:
        return ""

    cleaned = _THINK_RE.sub("", text)
    cleaned = _OPEN_THINK_RE.sub("", cleaned)

    candidates = []
    for match in _FENCE_RE.finditer(cleaned):
        body = (match.group(2) or "").strip()
        if _has_markup(body):
            candidates.append(body)
    if candidates:
        return max(candidates, key=lambda c: (_html_density(c), len(c))).strip()

    doc = re.search(r"(<!DOCTYPE\s+html[\s\S]*?(?:</html>|$)|<html[\s\S]*?(?:</html>|$))", cleaned, re.IGNORECASE)
    if doc and _has_markup(doc.group(1)):
        return doc.group(1).strip()

    start = re.search(
        r"<(?:div|section|main|header|footer|nav|article|aside|form|table|dialog|ul|ol|h[1-6]|p|button|a|img|input)\b",
        cleaned,
        re.IGNORECASE,
    )
    if start:
        snippet = cleaned[start.start():]
        # Remove prosa que veio depois do fechamento (texto sem tags no final).
        snippet = re.sub(r"```+$", "", snippet).strip()
        return snippet

    return cleaned.strip() if _has_markup(cleaned) else ""


def strip_thinking(text: str) -> str:
    cleaned = _THINK_RE.sub("", text or "")
    return _OPEN_THINK_RE.sub("", cleaned)


# ---------------------------------------------------------------------------
# Sanitização
# ---------------------------------------------------------------------------

def sanitize_html(html: str) -> str:
    """Remove scripts, iframes, handlers inline e URLs javascript:."""
    if not html:
        return ""

    for tag in DANGEROUS_TAGS:
        html = re.sub(rf"<{tag}\b[^>]*>[\s\S]*?</{tag}\s*>", "", html, flags=re.IGNORECASE)
        html = re.sub(rf"<{tag}\b[^>]*/?>", "", html, flags=re.IGNORECASE)

    # Atributos de evento (onclick, onload, ...) com ou sem aspas.
    html = re.sub(r'\s+on[a-zA-Z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', "", html)
    html = re.sub(r"""\s+on[a-zA-Z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", "", html)

    # URLs perigosas em href/src/action.
    html = re.sub(
        r"""((?:href|src|action|xlink:href)\s*=\s*)(["'])\s*javascript:[^"']*\2""",
        r"\1\2#\2",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(r"(<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]*>)", "", html, flags=re.IGNORECASE)
    return html


# ---------------------------------------------------------------------------
# Parser: reconstrução e balanceamento
# ---------------------------------------------------------------------------

class _Rebuilder(HTMLParser):
    """Reconstrói o HTML fechando tags implícitas e descartando fechamentos órfãos."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: List[str] = []
        self.stack: List[str] = []
        self.errors: List[str] = []
        self.missing: List[str] = []
        self._raw_stack: List[str] = []

    # -- helpers
    def _attrs_to_str(self, attrs) -> str:
        parts = []
        for name, value in attrs:
            if name.lower().startswith("on"):
                continue
            if value is None:
                parts.append(f" {name}")
            else:
                parts.append(f' {name}="{html_lib.escape(value, quote=True)}"')
        return "".join(parts)

    # -- parser hooks
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("html", "head", "body", "meta", "link", "title"):
            # Documento é reenvelopado por nós; não entra na árvore de conteúdo.
            if tag not in ("meta", "link"):
                return
        attr_str = self._attrs_to_str(attrs)
        if tag in VOID_TAGS:
            self.out.append(f"<{tag}{attr_str} />")
            return
        self.out.append(f"<{tag}{attr_str}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        self.out.append(f"<{tag}{self._attrs_to_str(attrs)} />")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("html", "head", "body", "title"):
            return
        if tag in VOID_TAGS:
            self.errors.append(f"Tag void </{tag}> descartada.")
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                missing = self.stack.pop()
                self.missing.append(missing)
                self.out.append(f"</{missing}>")
            self.stack.pop()
            self.out.append(f"</{tag}>")
        else:
            self.errors.append(f"Fechamento </{tag}> sem abertura correspondente (descartado).")

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        self.out.append(f"<!--{data}-->")

    def result(self) -> str:
        while self.stack:
            missing = self.stack.pop()
            self.missing.append(missing)
            self.out.append(f"</{missing}>")
        return "".join(self.out)


def rebuild_html(html: str) -> tuple[str, List[str], List[str]]:
    """Fecha tags pendentes e remove fechamentos órfãos. Retorna (html, erros, corrigidos)."""
    parser = _Rebuilder()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception as exc:  # HTMLParser é tolerante, mas nunca deixamos vazar
        return html or "", [f"Falha ao parsear HTML: {exc}"], []
    return parser.result(), parser.errors, parser.missing


def _strip_document(html: str) -> str:
    body = re.search(r"<body[^>]*>([\s\S]*?)</body\s*>", html, re.IGNORECASE)
    if body:
        return body.group(1).strip()
    html = re.sub(r"<!DOCTYPE[^>]*>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<head[\s\S]*?</head\s*>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</?(?:html|body|head)\b[^>]*>", "", html, flags=re.IGNORECASE)
    return html.strip()


def _visible_text(html: str) -> str:
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()


def _top_level_elements(html: str) -> List[str]:
    """Divide o HTML em elementos de primeiro nível (sem parser DOM externo)."""
    elements: List[str] = []
    depth = 0
    start: Optional[int] = None
    pattern = re.compile(r"<(/)?([a-zA-Z][a-zA-Z0-9:-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/)?>")
    for match in pattern.finditer(html or ""):
        closing, tag, _attrs, self_closing = match.groups()
        tag = tag.lower()
        if tag in ("html", "head", "body", "meta", "link", "title"):
            continue
        if start is None and not closing:
            start = match.start()
        if tag in VOID_TAGS or self_closing:
            if depth == 0 and start is not None:
                elements.append(html[start:match.end()].strip())
                start = None
            continue
        if closing:
            depth = max(0, depth - 1)
            if depth == 0 and start is not None:
                elements.append(html[start:match.end()].strip())
                start = None
        else:
            depth += 1
    if depth > 0 and start is not None:
        elements.append(html[start:].strip())
    return elements


def _ensure_unique_mb_ids(html: str) -> tuple[str, int, int]:
    """Garante data-mb-id único e presente nos elementos editáveis."""
    seen: set[str] = set()
    counter = 0
    injected = 0
    renamed = 0
    tag_counter: dict[str, int] = {}

    def replace(match: re.Match) -> str:
        nonlocal injected, renamed, counter
        attrs = match.group(2)
        id_match = re.search(r"""data-mb-id\s*=\s*(["'])(.*?)\1""", attrs, re.IGNORECASE)
        if id_match:
            value = id_match.group(2)
            if value in seen:
                counter += 1
                new_value = f"{value}-{counter}"
                renamed += 1
                seen.add(new_value)
                return match.group(0).replace(id_match.group(0), f'data-mb-id="{new_value}"', 1)
            seen.add(value)
            return match.group(0)

        tag = match.group(1).lower()
        tag_counter[tag] = tag_counter.get(tag, 0) + 1
        counter += 1
        new_id = f"mb-{tag}-{tag_counter[tag]}"
        while new_id in seen:
            counter += 1
            new_id = f"mb-{tag}-{counter}"
        seen.add(new_id)
        injected += 1
        return f"<{match.group(1)}{match.group(2)} data-mb-id=\"{new_id}\"{match.group(3)}>"

    pattern = re.compile(
        r"<([a-zA-Z][a-zA-Z0-9:-]*)((?:\s(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)?)(/?)>",
    )

    def repl(match: re.Match) -> str:
        tag = match.group(1).lower()
        if tag in VOID_TAGS or tag not in ID_TARGET_TAGS:
            return match.group(0)
        return replace(match)

    result = pattern.sub(repl, html or "")
    return result, injected, renamed


def wrap_document(body_html: str) -> str:
    body = _strip_document(body_html)
    return HTML_CANVAS_TEMPLATE.replace("__BODY_CONTENT__", f"  {body}\n")


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def _score(html: str, errors: List[str], warnings: List[str]) -> int:
    text = _visible_text(html)
    score = 100
    score -= 25 * len(errors)
    score -= 3 * len(warnings)
    if len(html) < 200:
        score -= 40
    if len(text) < 20:
        score -= 20
    if not re.search(r"<img\b", html, re.IGNORECASE):
        score -= 5
    if not re.search(r"""class=(["'])[^"']*(?:bg-|text-|flex|grid|p-|m-|rounded)""", html):
        score -= 10
    return max(0, min(100, score))


def validate_and_repair(
    raw_html: str,
    mode: str = "full",
    mb_id: Optional[str] = None,
    min_chars: int = 120,
    min_text_chars: int = 15,
) -> PatchValidation:
    """Valida um patch de LLM e devolve a melhor versão aplicável.

    `mode="full"` reenvelopa o documento completo; `mode="element"` mantém um
    único elemento de primeiro nível, preservando o `data-mb-id` do alvo.
    """
    errors: List[str] = []
    warnings: List[str] = []

    extracted = extract_html(raw_html) if raw_html else ""
    if not extracted:
        return PatchValidation(
            ok=False,
            html="",
            errors=["Nenhum HTML encontrado na resposta do modelo."],
            score=0,
        )

    cleaned = sanitize_html(extracted)

    if mode == "element":
        if re.search(r"<!DOCTYPE|<html\b|<body\b", cleaned, re.IGNORECASE):
            warnings.append("Documento completo recebido em edição de elemento; usando apenas o corpo/primeiro elemento.")
        body = _strip_document(cleaned)
        rebuilt, rebuild_errors, _ = rebuild_html(body)
        top = _top_level_elements(rebuilt)
        if not top:
            return PatchValidation(
                ok=False,
                html="",
                errors=["A resposta não contém nenhum elemento HTML de primeiro nível."],
                score=0,
            )
        if len(top) > 1:
            warnings.append(f"{len(top)} elementos de primeiro nível recebidos; apenas o primeiro foi aplicado.")
            errors.append("A edição de elemento deve devolver um único elemento raiz.")
        snippet = top[0]
        if mb_id and not re.search(rf"""data-mb-id\s*=\s*["']{re.escape(mb_id)}["']""", snippet):
            snippet = re.sub(
                r"^<([a-zA-Z][a-zA-Z0-9:-]*)",
                rf'<\1 data-mb-id="{mb_id}"',
                snippet,
                count=1,
            )
            warnings.append("data-mb-id do alvo reinserido.")
        snippet, _, _ = _ensure_unique_mb_ids(snippet)
        if len(snippet) < 10 or not _has_markup(snippet):
            errors.append("Fragmento de elemento vazio ou sem marcação.")
        if "<body" in snippet.lower() or "<html" in snippet.lower():
            errors.append("O fragmento ainda contém <html>/<body>.")

        ok = not errors
        score = _score(snippet, errors, warnings)
        return PatchValidation(
            ok=ok,
            html=snippet,
            errors=errors,
            warnings=warnings,
            score=score,
            metrics={"chars": len(snippet), "top_level": len(top)},
        )

    # --- documento completo
    # <style> iniciado e não fechado costuma indicar truncamento no meio do CSS.
    if re.search(r"<style", cleaned, re.IGNORECASE) and "</style>" not in cleaned.lower():
        cleaned = re.sub(r"<style[\s\S]*$", "", cleaned, flags=re.IGNORECASE).strip()
        warnings.append("<style> inacabado removido.")

    body_source = _strip_document(cleaned)
    if not body_source.strip():
        return PatchValidation(
            ok=False,
            html="",
            errors=["Documento vazio após remover <html>/<head>/<body>."],
            score=0,
        )

    rebuilt, rebuild_errors, fixed = rebuild_html(body_source)
    for tag in rebuild_errors:
        errors.append(tag)
    if fixed:
        warnings.append("Tags fechadas automaticamente: " + ", ".join(sorted(set(fixed))))

    if re.search(r"<style[\s\S]*$", rebuilt, re.IGNORECASE) and "</style>" not in rebuilt.lower():
        rebuilt = re.sub(r"<style[\s\S]*$", "", rebuilt, flags=re.IGNORECASE).strip()
        warnings.append("<style> inacabado removido.")

    rebuilt, injected, renamed = _ensure_unique_mb_ids(rebuilt)
    if injected:
        warnings.append(f"{injected} data-mb-id inserido(s) automaticamente.")
    if renamed:
        warnings.append(f"{renamed} data-mb-id duplicado(s) renomeado(s).")

    text = _visible_text(rebuilt)
    if len(rebuilt) < min_chars:
        errors.append(f"HTML muito curto ({len(rebuilt)} caracteres).")
    if len(text) < min_text_chars:
        errors.append("A tela não tem conteúdo textual visível.")

    for pattern in _LAZY_RE:
        if pattern.search(rebuilt):
            errors.append(f"Resumo/placeholder detectado: '{pattern.pattern}'.")
            break

    if not re.search(r"data-mb-id", rebuilt):
        errors.append("Nenhum data-mb-id presente após a reparação.")

    doc = wrap_document(rebuilt)
    score = _score(doc, errors, warnings)

    return PatchValidation(
        ok=not errors and score >= QUALITY_SCORE_MIN,
        html=doc,
        errors=errors,
        warnings=warnings,
        score=score,
        metrics={
            "chars": len(doc),
            "text_chars": len(text),
            "elements": _html_density(rebuilt),
        },
    )


def validate_section(raw_html: str) -> PatchValidation:
    """Validação leve de uma seção antes de montar o documento final."""
    extracted = extract_html(raw_html)
    if not extracted:
        return PatchValidation(ok=False, html="", errors=["Seção sem HTML."], score=0)

    cleaned = sanitize_html(_strip_document(extracted))
    rebuilt, rebuild_errors, fixed = rebuild_html(cleaned)
    rebuilt, injected, _ = _ensure_unique_mb_ids(rebuilt)
    top = _top_level_elements(rebuilt)
    errors = list(rebuild_errors)
    warnings: List[str] = []
    if fixed:
        warnings.append("Tags fechadas: " + ", ".join(sorted(set(fixed))))
    if not top:
        errors.append("Seção sem elementos.")
        rebuilt = ""
    if len(rebuilt) < 40:
        errors.append("Seção muito curta.")
    if _visible_text(rebuilt).strip() == "" and not re.search(r"<img\b", rebuilt, re.IGNORECASE):
        errors.append("Seção sem texto nem imagem.")
    for pattern in _LAZY_RE:
        if pattern.search(rebuilt):
            errors.append("Seção contém placeholder/resumo.")
            break

    return PatchValidation(
        ok=not errors,
        html=rebuilt,
        errors=errors,
        warnings=warnings,
        score=_score(rebuilt, errors, warnings),
        metrics={"chars": len(rebuilt), "elements": len(top)},
    )


def assemble_sections(sections: Iterable[str], root_class: str = "min-h-screen bg-[#09090b] text-slate-100 font-sans antialiased") -> PatchValidation:
    """Monta o documento completo a partir das seções geradas individualmente."""
    valid_sections = [s for s in sections if s and s.strip()]
    if not valid_sections:
        return PatchValidation(ok=False, html="", errors=["Nenhuma seção válida gerada."], score=0)

    inner = "\n".join(f"  {s.strip()}" for s in valid_sections)
    body = f'<div id="app-root" class="{root_class}">\n{inner}\n</div>'
    return validate_and_repair(body, mode="full", min_chars=200)
