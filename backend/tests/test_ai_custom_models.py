import os
import pytest
import httpx
import secrets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_ai_custom_models_flow():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        # 1. Registra usuário admin
        email = f"ai_tester_{secrets.token_hex(4)}@empresa.com"
        pwd = "SecureAiPassword123!"
        res_reg = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "AI Admin",
            "organization_name": f"Org AI {secrets.token_hex(3)}"
        })
        assert res_reg.status_code == 200, res_reg.text

        # 2. Configura Provedor com Modelos Customizados livres
        res_save = await client.post("/api/ai/providers", json={
            "provider_type": "custom",
            "api_key": "sk-dummy-test-key-987654",
            "default_model": "deepseek/deepseek-r1",
            "base_url": "https://api.deepseek.com/v1",
            "custom_models": [
                "deepseek/deepseek-r1",
                "qwen/qwen-2.5-coder-32b",
                "meu-modelo-personalizado:v2"
            ]
        })
        assert res_save.status_code == 200, res_save.text
        save_data = res_save.json()
        assert save_data["default_model"] == "deepseek/deepseek-r1"
        assert "meu-modelo-personalizado:v2" in save_data["custom_models"]

        # 3. Lista provedores e verifica se os modelos customizados persistem
        res_list = await client.get("/api/ai/providers")
        assert res_list.status_code == 200
        providers = res_list.json()
        found = [p for p in providers if p["provider_type"] == "custom"][0]
        assert "meu-modelo-personalizado:v2" in found["custom_models"]
        assert found["base_url"] == "https://api.deepseek.com/v1"

        # 4. Envia instrução ao Chat usando o modelo customizado
        res_chat = await client.post("/api/ai/chat", json={
            "prompt": "Crie um card de faturamento mensal",
            "model_name": "meu-modelo-personalizado:v2",
            "current_html": ""
        })
        assert res_chat.status_code == 200, res_chat.text
        chat_data = res_chat.json()
        # Como sk-dummy não é uma chave real na DeepSeek, a API retorna erro 401 autenticado do upstream
        assert ("suggested_patch" in chat_data) or ("retornou erro" in chat_data.get("detail", "").lower())

        # 5. Testa o endpoint de test-connection
        res_test = await client.post("/api/ai/test-connection", json={
            "provider_type": "custom",
            "api_key": "sk-test",
            "base_url": "http://127.0.0.1:9999/v1",
            "model_name": "meu-modelo-personalizado:v2"
        })
        assert res_test.status_code == 200
        test_data = res_test.json()
        assert "status" in test_data
