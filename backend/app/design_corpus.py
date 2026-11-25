"""Importação e exportação do corpus `design/` do Mockbird v1.

O repositório antigo gerava, dentro do projeto do cliente, uma pasta `design/`
com um `tokens.json` e uma subpasta por canvas:

    design/
      tokens.json
      login/
        canvas.json
        01-login.html
        02-cadastro.html
      checkout/
        canvas.json
        01-carrinho.html

Cada `canvas.json` descreve as telas daquela pasta::

    {"title": "Login", "screens": [
        {"id": "login", "name": "Login", "file": "01-login.html",
         "device": "mobile", "width": 390, "height": 844}
    ]}

Este módulo converte esse formato para o modelo do app (Canvas + Screen +
DesignTokens) e faz o caminho inverso para o export. As funções aqui são puras
(não tocam no banco) para poderem ser testadas sem infraestrutura.
"""

from __future__ import annotations

import io
import json
import posixpath
import re
import unicodedata
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_SCREENS = 300

_CSS_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_REL_RE = re.compile(r"""rel\s*=\s*["']?([^"'\s>]+)""", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>\s*</script>""",
    re.IGNORECASE,
)


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")


class DesignCorpusError(ValueError):
    """Arquivo de corpus inválido ou fora dos limites aceitos."""


# --------------------------------------------------------------------- utils


def _slugify(value: str) -> str:
    clean = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ASCII", "ignore")
        .decode("ASCII")
    )
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", clean).strip("-").lower()
    return slug or "tela"


def _device_type(raw: Optional[str], width: int) -> str:
    value = (raw or "").strip().lower()
    if value in {"mobile", "tablet", "desktop", "custom"}:
        return value
    if value in {"phone", "smartphone"}:
        return "mobile"
    if value in {"laptop", "screen", "web"}:
        return "desktop"
    if width <= 480:
        return "mobile"
    if width <= 1024:
        return "tablet"
    return "desktop"


_IGNORED_PARTS = {"snapshots", ".visual", "node_modules", ".git", ".cache"}


def _is_ignored_path(path: str) -> bool:
    """Ignora snapshots/backups: eles duplicam canvases já importados."""
    for part in path.split("/"):
        lowered = part.lower()
        if lowered in _IGNORED_PARTS or "backup" in lowered:
            return True
        if lowered.endswith((".new", ".bak", ".orig")):
            return True
    return False


def _is_external(href: str) -> bool:
    lowered = href.strip().lower()
    return (
        not lowered
        or lowered.startswith(("http://", "https://", "//", "data:", "mailto:"))
    )


# ------------------------------------------------------------------- archive


def read_archive(blob: bytes) -> Dict[str, bytes]:
    """Lê o ZIP para um mapa caminho-normalizado -> bytes, com limites."""
    if len(blob) > MAX_ARCHIVE_BYTES:
        raise DesignCorpusError(
            f"Arquivo maior que o limite de {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB."
        )
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        raise DesignCorpusError("Envie um arquivo .zip com a pasta design/ do projeto antigo.")

    files: Dict[str, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise DesignCorpusError("ZIP com arquivos demais.")
            for info in infos:
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                parts = [p for p in name.split("/") if p not in ("", ".")]
                if not parts or name.startswith("/") or ".." in parts:
                    continue
                if parts[0] == "__MACOSX" or parts[-1] in {".DS_Store", "Thumbs.db"}:
                    continue
                normalized = "/".join(parts)
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise DesignCorpusError("Conteúdo descompactado acima do limite.")
                files[normalized] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise DesignCorpusError("ZIP corrompido ou ilegível.") from exc
    return files


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# -------------------------------------------------------------------- tokens


def flatten_tokens(node: Any, prefix: str = "") -> Dict[str, Any]:
    """Achata tokens DTCG (`{"color": {"bg": {"$value": "#fff"}}}`)."""
    flat: Dict[str, Any] = {}
    if not isinstance(node, dict):
        if prefix:
            flat[prefix] = node
        return flat
    if "$value" in node and not isinstance(node["$value"], dict):
        flat[prefix] = node["$value"]
        return flat
    for key, value in node.items():
        if key.startswith("$"):
            continue
        child = f"{prefix}-{key}" if prefix else key
        flat.update(flatten_tokens(value, child))
    return flat


def nest_tokens(flat: Dict[str, Any]) -> Dict[str, Any]:
    """Faz o caminho inverso: `color-primary` -> `color.primary.$value`."""
    nested: Dict[str, Any] = {}
    for name, value in (flat or {}).items():
        parts = [p for p in str(name).split("-") if p]
        if not parts:
            continue
        cursor = nested
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = {"$value": value}
        if parts and parts[0] == "color":
            nested.setdefault("color", {})["$type"] = "color"
    return nested


def extract_tokens(files: Dict[str, bytes]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Encontra o tokens.json do corpus e devolve light/dark/shared achatados."""
    candidates = sorted(
        (path for path in files if posixpath.basename(path) == "tokens.json"),
        key=lambda path: (path.count("/"), path),
    )
    for path in candidates:
        try:
            raw = json.loads(_decode(files[path]))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        if not {"light", "dark", "shared"} & set(raw.keys()):
            continue
        return (
            flatten_tokens(raw.get("light") or {}),
            flatten_tokens(raw.get("dark") or {}),
            flatten_tokens(raw.get("shared") or raw.get("$extensions") or {}),
        )
    return {}, {}, {}


# ---------------------------------------------------------------------- html


def _resolve_asset(href: str, html_path: str, files: Dict[str, bytes]) -> Optional[str]:
    if _is_external(href):
        return None
    target = posixpath.normpath(
        posixpath.join(posixpath.dirname(html_path), href.split("?")[0].split("#")[0])
    )
    if target in files:
        return target
    # Alguns corpora referenciam a raiz do design/ com ../ a partir de subpastas.
    fallback = posixpath.normpath(href.split("?")[0].split("#")[0]).lstrip("./")
    if fallback in files:
        return fallback
    return None


def inline_assets(html: str, html_path: str, files: Dict[str, bytes]) -> str:
    """Inlina CSS/JS locais referenciados pela tela (o srcDoc não resolve ../)."""

    def replace_link(match: re.Match[str]) -> str:
        tag = match.group(0)
        rel = _REL_RE.search(tag)
        if not rel or "stylesheet" not in rel.group(1).lower():
            return tag
        href = _HREF_RE.search(tag)
        if not href:
            return tag
        target = _resolve_asset(href.group(1), html_path, files)
        if not target:
            return tag
        return f"<style>\n{_decode(files[target])}\n</style>"

    def replace_script(match: re.Match[str]) -> str:
        target = _resolve_asset(match.group(1), html_path, files)
        if not target:
            return match.group(0)
        content = _decode(files[target]).replace("</script", "<\\/script")
        return f"<script>\n{content}\n</script>"

    html = _CSS_LINK_RE.sub(replace_link, html)
    html = _SCRIPT_SRC_RE.sub(replace_script, html)
    return html


# --------------------------------------------------------------------- parse


def parse_design_corpus(blob: bytes) -> Dict[str, Any]:
    """Converte o ZIP do corpus v1 em canvases/telas prontos para persistir."""
    files = read_archive(blob)
    canvas_files = sorted(
        path
        for path in files
        if posixpath.basename(path) == "canvas.json" and not _is_ignored_path(path)
    )
    light, dark, shared = extract_tokens(files)
    canvases: List[Dict[str, Any]] = []
    warnings: List[str] = []
    screen_count = 0

    if not canvas_files:
        # Fallback inteligente: auto-detecta arquivos .html no ZIP quando canvas.json não está presente
        html_files = sorted(
            path
            for path in files
            if path.lower().endswith(".html") and not _is_ignored_path(path)
        )
        if not html_files:
            raise DesignCorpusError(
                "Nenhum arquivo .html ou canvas.json encontrado no arquivo ZIP."
            )

        folders_map: Dict[str, List[str]] = {}
        for hpath in html_files:
            folder = posixpath.dirname(hpath)
            c_name = posixpath.basename(folder) if folder else "Principal"
            if c_name.lower() in {"design", "out", "out4", "screens", "html", "dist", "."}:
                c_name = "Principal"
            folders_map.setdefault(c_name, []).append(hpath)

        for c_name, hpaths in folders_map.items():
            screens = []
            for hpath in hpaths:
                stem = posixpath.splitext(posixpath.basename(hpath))[0]
                clean_name = re.sub(r"^\d+[\-_]", "", stem).replace("_", " ").replace("-", " ").strip().title()
                if not clean_name:
                    clean_name = stem
                is_mob = "mobile" in stem.lower()
                w, h = (375, 812) if is_mob else (1440, 900)
                html_raw = _decode(files[hpath])
                html_inlined = inline_assets(html_raw, hpath, files)
                screens.append({
                    "name": clean_name,
                    "html_content": html_inlined,
                    "width": w,
                    "height": h,
                    "device_type": "mobile" if is_mob else "desktop",
                    "screen_kind": "page",
                    "group": None,
                })
                screen_count += 1
            if screens:
                canvases.append({"name": c_name, "screens": screens})
    else:
        for canvas_path in canvas_files:
            try:
                raw = json.loads(_decode(files[canvas_path]))
            except (json.JSONDecodeError, UnicodeDecodeError):
                warnings.append(f"{canvas_path}: JSON inválido, canvas ignorado.")
                continue
            if not isinstance(raw, dict):
                continue

            folder = posixpath.dirname(canvas_path)
            name = str(raw.get("title") or raw.get("name") or posixpath.basename(folder) or "Canvas")
            screens: List[Dict[str, Any]] = []
            for item in raw.get("screens") or []:
                if not isinstance(item, dict):
                    continue
                file_ref = str(item.get("file") or "")
                if not file_ref:
                    warnings.append(f"{canvas_path}: tela sem arquivo, ignorada.")
                    continue
                html_path = posixpath.normpath(posixpath.join(folder, file_ref))
                if html_path not in files:
                    warnings.append(f"{html_path}: arquivo da tela não está no ZIP.")
                    continue
                if screen_count >= MAX_SCREENS:
                    warnings.append("Limite de telas por importação atingido; restante ignorado.")
                    break
                try:
                    width = int(item.get("width") or 1440)
                    height = int(item.get("height") or 900)
                except (TypeError, ValueError):
                    width, height = 1440, 900
                html = inline_assets(_decode(files[html_path]), html_path, files)
                screens.append(
                    {
                        "name": str(item.get("name") or item.get("id") or posixpath.basename(html_path)),
                        "html_content": html,
                        "width": width,
                        "height": height,
                        "device_type": _device_type(item.get("device"), width),
                        "screen_kind": "modal_overlay" if "modal" in str(item.get("id", "")).lower() else "page",
                        "group": item.get("group"),
                    }
                )
                screen_count += 1

            if screens:
                canvases.append({"name": name, "screens": screens})
            else:
                warnings.append(f"{canvas_path}: nenhuma tela válida.")

    if not canvases:
        raise DesignCorpusError("O corpus não tem nenhuma tela importável.")

    assets_map: Dict[str, bytes] = {}
    for file_path, file_data in files.items():
        lowered = file_path.lower()
        if any(lowered.endswith(ext) for ext in IMAGE_EXTENSIONS) and not _is_ignored_path(file_path):
            assets_map[file_path] = file_data

    return {
        "tokens": {"light": light, "dark": dark, "shared": shared},
        "canvases": canvases,
        "assets": assets_map,
        "warnings": warnings,
        "screen_count": screen_count,
    }


# -------------------------------------------------------------------- export


def _ensure_document(screen: Dict[str, Any], tokens_css: str) -> str:
    html = (screen.get("html_content") or "").strip()
    if "<html" in html.lower() or "<!doctype" in html.lower():
        return html
    css = (screen.get("css_content") or "").strip()
    js = (screen.get("js_content") or "").strip()
    title = re.sub(r"[<>&]", "", str(screen.get("name") or "Tela"))
    return (
        "<!doctype html>\n"
        '<html lang="pt-BR" data-theme="light">\n<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{title}</title>\n"
        f"  <style>:root {{\n{tokens_css}\n}}</style>\n"
        f"  <style>\n{css}\n</style>\n"
        "</head>\n<body>\n"
        f"{html}\n"
        + (f"<script>\n{js}\n</script>\n" if js else "")
        + "</body>\n</html>\n"
    )


def build_design_corpus(
    project_name: str,
    tokens: Dict[str, Dict[str, Any]],
    canvases: Iterable[Dict[str, Any]],
) -> bytes:
    """Gera o ZIP no layout `design/` do v1 a partir do estado atual do app."""
    light = nest_tokens(tokens.get("light") or {})
    dark = nest_tokens(tokens.get("dark") or {})
    tokens_css = "\n".join(
        f"  --{key.replace('_', '-')}: {value};"
        for key, value in (tokens.get("light") or {}).items()
    )

    buffer = io.BytesIO()
    used_dirs: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "design/tokens.json",
            json.dumps({"light": light, "dark": dark}, indent=2) + "\n",
        )
        for canvas_index, canvas in enumerate(canvases):
            canvas_name = str(canvas.get("name") or f"Canvas {canvas_index + 1}")
            base = _slugify(canvas_name)
            folder = base
            suffix = 2
            while folder in used_dirs:
                folder = f"{base}-{suffix}"
                suffix += 1
            used_dirs.add(folder)

            entries: List[Dict[str, Any]] = []
            for screen_index, screen in enumerate(canvas.get("screens") or []):
                screen_name = str(screen.get("name") or f"Tela {screen_index + 1}")
                filename = f"{screen_index + 1:02d}-{_slugify(screen_name)}.html"
                entries.append(
                    {
                        "id": _slugify(screen_name),
                        "name": screen_name,
                        "file": filename,
                        "device": screen.get("device_type") or "desktop",
                        "width": screen.get("width") or 1440,
                        "height": screen.get("height") or 900,
                    }
                )
                archive.writestr(
                    f"design/{folder}/{filename}",
                    _ensure_document(screen, tokens_css),
                )

            archive.writestr(
                f"design/{folder}/canvas.json",
                json.dumps({"title": canvas_name, "screens": entries}, indent=2) + "\n",
            )
        archive.writestr(
            "design/README.md",
            f"# {project_name}\n\nCorpus exportado do Mockbird v2 "
            "(tokens.json + uma pasta por canvas com canvas.json e telas .html).\n",
        )
    return buffer.getvalue()
