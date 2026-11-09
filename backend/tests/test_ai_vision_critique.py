import pytest
import httpx
import secrets
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")


@pytest.mark.asyncio
async def test_ai_vision_critique_endpoint():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        email = f"vision_user_{secrets.token_hex(4)}@empresa.com"
        pwd = "VisionPass123!"

        reg_res = await client.post("/api/auth/register", json={
            "email": email,
            "password": pwd,
            "name": "Vision Tester",
            "organization_name": f"Org Vision {secrets.token_hex(3)}"
        })
        assert reg_res.status_code == 200, reg_res.text

        csrf = client.cookies.get("mockbird_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        # Envia requisição com HTML simples e pedido de carro da Honda
        payload = {
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "current_html": "<div class='p-4'><h1>Site</h1><p>Carro</p></div>",
            "prompt": "Cria para mim uma tela de um website de venda de carro da Honda",
            "model_name": "bonsai-27b"
        }
        res = await client.post(
            "/api/ai/vision-critique",
            headers=headers,
            json=payload,
            timeout=120.0
        )
        assert res.status_code == 200, f"Status={res.status_code}, text={res.text}"
        data = res.json()
        assert data["status"] == "success"
        assert "vision_critique" in data
        assert "refined_html" in data
        assert len(data["refined_html"]) > 0
        print("\n[TEST VISION CRITIQUE SUCESSO]:", data["vision_critique"][:160])
