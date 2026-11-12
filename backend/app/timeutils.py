"""Utilidades de tempo.

As colunas do banco são `TIMESTAMP WITHOUT TIME ZONE`, então mantemos o padrão
de UTC ingênuo — mas sem a API `datetime.utcnow()`, deprecada no Python 3.12.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
