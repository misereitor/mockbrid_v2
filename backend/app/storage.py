"""Armazenamento local de assets (imagens) enviados pelos usuários.

O diretório é configurável por `ASSETS_DIR`; para múltiplas réplicas troque
`save_asset`/`asset_path` por um backend de objeto (S3/GCS) mantendo a API.
"""

import os
import re
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings

# Tipo real detectado pelos magic bytes -> extensão usada no disco.
ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def sanitize_svg(data: bytes) -> bytes:
    """Remove scripts, handlers on* e elementos perigosos de arquivos SVG contra XSS."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin1", errors="replace")

    # Remove tags <script>...</script> e variantes
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<script\b[^>]*/>", "", text)
    # Remove tags <foreignObject>...</foreignObject>
    text = re.sub(r"(?is)<foreignObject\b[^>]*>.*?</foreignObject>", "", text)
    # Remove atributos de eventos on* (onload, onclick, onerror, etc.)
    text = re.sub(r"""(?is)\bon[a-z0-9_-]+\s*=\s*(?:'[^']*'|"[^"]*"|[^\s>]+)""", "", text)
    # Remove URIs javascript:
    text = re.sub(r"""(?is)(?:href|src|xlink:href)\s*=\s*['"]\s*javascript:[^'"]*['"]""", 'href="#"', text)

    return text.encode("utf-8")


def sniff_image_type(head: bytes) -> Optional[str]:
    """Detecta o tipo pelo conteúdo, nunca pelo nome/extensão enviados."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"<svg") or (stripped.startswith(b"<?xml") and b"<svg" in head[:512]):
        return "image/svg+xml"
    return None


def assets_root() -> Path:
    root = Path(settings.ASSETS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(project_id: str) -> Path:
    # project_id vem do banco (uuid), mas sanitizamos por garantia.
    safe = "".join(ch for ch in project_id if ch.isalnum() or ch in "-_")
    path = assets_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_asset(project_id: str, data: bytes, content_type: str) -> str:
    if content_type == "image/svg+xml":
        data = sanitize_svg(data)
    filename = f"{uuid.uuid4().hex}{ALLOWED_TYPES[content_type]}"
    target = project_dir(project_id) / filename
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(target)
    return filename


def asset_path(project_id: str, filename: str) -> Optional[Path]:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = project_dir(project_id) / filename
    if not path.is_file():
        return None
    return path


def delete_asset(project_id: str, filename: str) -> None:
    path = asset_path(project_id, filename)
    if path:
        try:
            path.unlink()
        except OSError:
            pass
