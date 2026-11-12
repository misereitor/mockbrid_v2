import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_ai_chat_conversations_history_and_quota_block():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Registra usuário e cria projeto com tela
        email = f"chat_user_{secrets.token_hex(4)}@empresa.com"
        pwd = "ChatPass123!"
        reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Chat Designer",
            "organization_name": f"Org Chat {secrets.token_hex(3)}"
        })
        assert reg.status_code == 200
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Cria projeto
        proj_res = await client.post("/api/projects", json={
            "name": "Projeto com Chat IA"
        }, headers=headers)
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["id"]
        screen_id = proj_res.json()["entry_screen_id"]

        # 2. Cria conversa no servidor
        conv_res = await client.post("/api/ai/conversations", json={
            "title": "Refatoração do Cabeçalho",
            "project_id": proj_id,
            "screen_id": screen_id
        }, headers=headers)
        assert conv_res.status_code == 200
        conv = conv_res.json()
        conv_id = conv["id"]
        assert conv["title"] == "Refatoração do Cabeçalho"

        # 3. Lista conversas do usuário
        list_conv = await client.get("/api/ai/conversations")
        assert list_conv.status_code == 200
        conv_ids = [c["id"] for c in list_conv.json()]
        assert conv_id in conv_ids

    # 4. Outro usuário tenta ler as mensagens dessa conversa -> 404
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as stranger_client:
        stranger_email = f"stranger_{secrets.token_hex(4)}@empresa.com"
        await stranger_client.post("/api/auth/register", json={
            "email": stranger_email,
            "password": pwd,
            "name": "Estranho",
            "organization_name": f"Org Stranger {secrets.token_hex(3)}"
        })
        hack_res = await stranger_client.get(f"/api/ai/conversations/{conv_id}/messages")
        assert hack_res.status_code == 404, "Histórico de conversa de outro usuário não pode ser acessado"

    # 5. Executa o chat de IA associado ao screen_id e conversation_id
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        await client.post("/api/auth/login", json={"email": email, "password": pwd})
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Executa chat com screen_id oficial do banco
        async with client.stream(
            "POST",
            "/api/ai/agent/stream",
            json={
                "prompt": "Explique brevemente a estrutura desta tela",
                "screen_id": screen_id,
                "conversation_id": conv_id,
                "model_name": "bonsai-27b"
            },
            headers=headers
        ) as res:
            assert res.status_code == 200
            async for line in res.aiter_lines():
                pass

        # 6. Verifica que as mensagens foram salvas no servidor
        msgs_res = await client.get(f"/api/ai/conversations/{conv_id}/messages")
        assert msgs_res.status_code == 200
        messages = msgs_res.json()
        assert len(messages) >= 2, f"Mensagens não foram persistidas: {messages}"
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    # 7. Teste de Bloqueio por Cota Ultrapassada (429)
    # Simula cota estourada atualizando o banco ou chamando com limite baixo

    # Vamos atualizar diretamente o user de teste para ter tokens_used_month >= monthly_token_limit
    import asyncpg
    conn = await asyncpg.connect("postgresql://mockbird:mockbird_homolog_secret@127.0.0.1:5434/mockbird_v2")
    try:
        await conn.execute("UPDATE users SET tokens_used_month = 250000, monthly_token_limit = 200000 WHERE email = $1", email)
    finally:
        await conn.close()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        await client.post("/api/auth/login", json={"email": email, "password": pwd})
        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Chamada deve falhar imediatamente com 429
        quota_res = await client.post("/api/ai/agent/stream", json={
            "prompt": "Esta chamada deve ser barrada por cota",
            "screen_id": screen_id
        }, headers=headers)
        assert quota_res.status_code == 429, f"Cota ultrapassada deveria retornar 429, retornou: {quota_res.status_code}"
        assert "limite mensal de tokens" in quota_res.json()["detail"].lower()
