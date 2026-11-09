import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


def _get_fernet_key() -> bytes:
    """Retorna uma chave Fernet válida de 32 bytes url-safe base64."""
    configured_key = getattr(settings, "ENCRYPTION_KEY", "")
    if configured_key and len(configured_key.strip()) > 0:
        raw_key = configured_key.strip()
        # Se já for 44 caracteres terminados em = (Fernet format)
        try:
            decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
            if len(decoded) == 32:
                return raw_key.encode("utf-8")
        except Exception:
            pass

    # Derivação determinística a partir de SECRET_KEY via SHA256
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plain_text: Optional[str]) -> str:
    """Criptografa uma string sensível (ex: API key) usando Fernet."""
    if not plain_text or not plain_text.strip():
        return ""
    fernet = Fernet(_get_fernet_key())
    encrypted = fernet.encrypt(plain_text.strip().encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_secret(cipher_text: Optional[str]) -> str:
    """Descriptografa uma string cifrada. Possui fallback suave para dados legados em texto puro."""
    if not cipher_text or not cipher_text.strip():
        return ""
    text = cipher_text.strip()
    # Verifica se parece um token Fernet
    if text.startswith("gAAAAA"):
        try:
            fernet = Fernet(_get_fernet_key())
            decrypted = fernet.decrypt(text.encode("utf-8"))
            return decrypted.decode("utf-8")
        except (InvalidToken, Exception):
            pass
    # Fallback se for legado em plain-text
    return text

