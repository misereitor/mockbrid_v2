import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models import User, Organization, AIProvider
from app.database import AsyncSessionLocal
from app.routes_auth import create_access_token


@pytest.mark.asyncio
async def test_ai_vision_critique_endpoint():
    async with AsyncSessionLocal() as session:
        # Pega ou cria usuário de teste
        from sqlalchemy.future import select
        res = await session.execute(select(User).limit(1))
        user = res.scalars().first()
        if not user:
            org = Organization(name="Vision Test Org", slug="vision-test-org")
            session.add(org)
            await session.commit()
            await session.refresh(org)
            user = User(
                email="vision_test@mockbird.local",
                hashed_password="dummy",
                name="Vision Tester",
                role="owner",
                organization_id=org.id
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

    token = create_access_token({"sub": user.id, "org": user.organization_id})
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Envia requisição com HTML simples e pedido de carro da Honda
        payload = {
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "current_html": "<div class='p-4'><h1>Site</h1><p>Carro</p></div>",
            "prompt": "Cria para mim uma tela de um website de venda de carro da Honda",
            "model_name": "bonsai-27b"
        }
        res = await client.post(
            "/api/ai/vision-critique",
            headers={"Authorization": f"Bearer {token}"},
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
