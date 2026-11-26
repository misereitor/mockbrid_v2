"""Configuração dos testes.

A suíte E2E original exige a stack de homologação em `BASE_URL`. Sem ela, os
testes eram falhas de conexão em vez de skips. Aqui detectamos a stack uma vez
e marcamos como `skip` apenas os módulos que dependem dela; testes unitários
(jsx, authz, crypto, rate limit) continuam rodando sempre.
"""

import os

# `app.config` valida o ambiente ao ser importado e o padrão é "production"
# (estrito). A suíte roda como `test`; precisa ser definido antes de qualquer
# import de `app.*`. Atribuição direta (e não setdefault) para que um
# ENVIRONMENT=production vazado do shell não derrube a coleta dos testes.
os.environ["ENVIRONMENT"] = "test"

import httpx  # noqa: E402
import pytest  # noqa: E402

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


def _stack_is_up() -> bool:
    try:
        response = httpx.get(f"{BASE_URL}/api/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    stack_up = _stack_is_up()
    if stack_up:
        return

    skip_e2e = pytest.mark.skip(reason=f"stack de homologação indisponível em {BASE_URL}")
    for item in items:
        module = getattr(item, "module", None)
        if module is not None and hasattr(module, "BASE_URL"):
            item.add_marker(skip_e2e)
