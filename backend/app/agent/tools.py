import re
from typing import Dict, Any, Optional, List
from app.agent.state import QualityAudit


def extract_dom_structure(html: str) -> str:
    """Extrai uma representação compacta da estrutura do DOM para a IA planejar sem estourar tokens."""
    if not html:
        return "DOM Vazio (sem elementos)."

    tags = re.findall(r'<([a-zA-Z0-9\-]+)([^>]*)>', html)
    structure_lines = []
    
    for tag, attrs in tags:
        tag_lower = tag.lower()
        if tag_lower in ['meta', 'link', 'script', 'style', 'br', 'hr']:
            continue
        
        # Procura data-mb-id ou id
        id_match = re.search(r'data-mb-id=["\']([^"\']+)["\']', attrs) or re.search(r'id=["\']([^"\']+)["\']', attrs)
        class_match = re.search(r'class=["\']([^"\']+)["\']', attrs)
        
        identifier = f"#{id_match.group(1)}" if id_match else ""
        classes = class_match.group(1)[:40] + "…" if class_match and len(class_match.group(1)) > 40 else (class_match.group(1) if class_match else "")
        
        line = f"<{tag_lower}{identifier}>"
        if classes:
            line += f" (classes: {classes})"
        
        if len(structure_lines) < 30:
            structure_lines.append(line)

    if len(structure_lines) == 0:
        return "Estrutura simples sem identificadores."
        
    return "\n".join(structure_lines[:30]) + (f"\n... (+{len(tags) - 30} elementos)" if len(tags) > 30 else "")


def extract_element_snippet(html: str, target_identifier: str) -> Optional[str]:
    """Extrai o bloco HTML completo de um elemento pelo seu data-mb-id ou id."""
    if not html or not target_identifier:
        return None
    clean_id = target_identifier.lstrip('#').strip()
    pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_id)}["\'][\s\S]*?</\2>)'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Se for tag autocontida (img, input)
    self_pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_id)}["\'][^>]*\/?>)'
    m_self = re.search(self_pattern, html, re.IGNORECASE)
    if m_self:
        return m_self.group(1).strip()
    return None


def diagnose_layout_issues(html: str) -> List[str]:
    """Verifica possíveis quebras de layout comuns em HTML/Tailwind."""
    issues = []
    if not html or len(html.strip()) < 50:
        return ["Documento HTML vazio ou quase sem conteúdo."]

    # Checa tags não fechadas comuns (div, section, main, header, footer)
    for tag in ['div', 'section', 'main', 'header', 'footer', 'article']:
        open_count = len(re.findall(rf'<{tag}\b[^>]*>', html, re.IGNORECASE))
        close_count = len(re.findall(rf'</{tag}>', html, re.IGNORECASE))
        if open_count != close_count:
            issues.append(f"Desbalanceamento de tags <{tag}>: {open_count} abertas vs {close_count} fechadas.")

    # Checa se há conflitos comuns de layout
    if "overflow-hidden" in html and "h-screen" in html and "overflow-y-auto" not in html:
        issues.append("Container com h-screen e overflow-hidden sem área de rolagem interna (conteúdo pode estar cortado).")

    if "<img" in html and not re.search(r'<img[^>]+src=["\']https?://[^"\']+["\']', html):
        issues.append("Imagens sem atributo src ou com URL quebrada/vazia.")

    return issues


def patch_canvas_section(full_html: str, target_selector: str, new_snippet: str) -> str:
    """Substitui cirurgicamente uma seção específica da tela ou a tela inteira."""
    if not full_html or target_selector in ["root", "full", "body"]:
        return new_snippet.strip()

    clean_target = target_selector.lstrip('#').strip()
    
    # Tenta casar por data-mb-id ou id
    pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_target)}["\'][\s\S]*?</\2>)'
    if re.search(pattern, full_html, re.IGNORECASE):
        return re.sub(pattern, new_snippet.strip(), full_html, count=1, flags=re.IGNORECASE)

    # Se for tag autocontida
    self_pattern = rf'(<([a-zA-Z0-9\-]+)[^>]*(?:data-mb-id|id)=["\']{re.escape(clean_target)}["\'][^>]*\/?>)'
    if re.search(self_pattern, full_html, re.IGNORECASE):
        return re.sub(self_pattern, new_snippet.strip(), full_html, count=1, flags=re.IGNORECASE)

    # Se não encontrou alvo cirúrgico, devolve o novo snippet se for documento completo
    if "<body" in new_snippet or "<html" in new_snippet or "<!DOCTYPE" in new_snippet:
        return new_snippet.strip()
        
    return full_html


# Palavras que denunciam que a IA teve preguiça e resumiu o código em vez de programar
LAZY_OUTLINE_PATTERNS = [
    r'noise\s+overlay\s+div',
    r'hero\s+(?:section\s+)?div',
    r'marquee\s+(?:section\s+)?div',
    r'modelos\s+\(bento\s+grid\)',
    r'engenharia\s+\(sticky',
    r'financas\s+\(simulator\)',
    r'test-drive\s+\(CTA',
    r'footer\s+div',
    r'<!--\s*(?:insira|adicione|adicione aqui|coloque aqui|todo|restante|código continua)\s*-->',
    r'\[\s*(?:insira|coloque|todo|placeholder)\s*\]',
    r'Lorem\s+ipsum\s+dolor',
]


def verify_ui_quality(html: str) -> QualityAudit:
    """Valida a qualidade do código gerado, garantindo que não seja resumo ou pseudo-código."""
    issues = []
    suggestions = []
    score = 100

    if not html or len(html.strip()) < 100:
        return QualityAudit(
            passed=False,
            score=10,
            issues=["Código HTML excessivamente curto ou vazio."],
            suggestions=["Gere o documento ou elemento com estrutura completa."]
        )

    # 1. Verifica resumos preguiçosos
    for pat in LAZY_OUTLINE_PATTERNS:
        if re.search(pat, html, re.IGNORECASE):
            issues.append(f"Detectado resumo/pseudo-código preguiçoso compatível com padrão '{pat}'.")
            score -= 30

    # 2. Verifica presença de tags fundamentais
    if "<" not in html or ">" not in html:
        issues.append("HTML não contém tags válidas.")
        score -= 50

    # 3. Verifica se tem elementos de imagem reais (Unsplash ou URLs válidas) se for página completa
    if "<body" in html or "<html" in html:
        has_img = bool(re.search(r'<img[^>]+src=["\']https?://[^"\']+["\']', html))
        if not has_img:
            suggestions.append("Adicione imagens reais do Unsplash para enriquecer o visual.")
            score -= 10

    # 4. Verifica classes de estilo (Tailwind ou CSS inline)
    has_styles = bool(re.search(r'class=["\'][^"\']*(?:bg-|text-|flex|grid|p-|m-|rounded)[^"\']*["\']', html))
    if not has_styles:
        suggestions.append("Use classes utilitárias do Tailwind CSS para garantir contraste e tipografia refinada.")
        score -= 15

    # 5. Verifica data-mb-id para suporte ao canvas
    has_mb_ids = "data-mb-id" in html
    if not has_mb_ids:
        suggestions.append("Adicione identificadores data-mb-id nos componentes para permitir inspeção no canvas.")

    passed = (score >= 70) and (len(issues) == 0)

    return QualityAudit(
        passed=passed,
        score=max(0, score),
        issues=issues,
        suggestions=suggestions
    )
