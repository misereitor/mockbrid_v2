import asyncio
import json
import os
import secrets
import struct
import zlib

import httpx
import pytest
import websockets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8082")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8082")
PASSWORD = "PasswordStrong123!"


def png_bytes() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


async def _new_tenant(client: httpx.AsyncClient):
    email = f"t_{secrets.token_hex(4)}@empresa.com"
    res = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Tenant Teste",
            "organization_name": f"Org {secrets.token_hex(3)}",
        },
    )
    assert res.status_code == 200, res.text
    csrf = client.cookies.get("mockbird_csrf")
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    project = (await client.post("/api/projects", json={"name": "Projeto"}, headers=headers)).json()
    return project, headers, email


@pytest.mark.asyncio
async def test_assets_upload_validation_and_public_serving():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        project, headers, _ = await _new_tenant(owner)

        ok = await owner.post(
            f"/api/projects/{project['id']}/assets",
            files={"file": ("logo.png", png_bytes(), "image/png")},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        asset = ok.json()
        assert asset["content_type"] == "image/png"
        assert asset["url"].startswith("/api/assets/")

        bad = await owner.post(
            f"/api/projects/{project['id']}/assets",
            files={"file": ("x.svg", b"<svg onload=alert(1)>", "image/svg+xml")},
            headers=headers,
        )
        assert bad.status_code == 415

        assert (await owner.get(asset["url"])).status_code == 200

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            assert (await anon.get(asset["url"])).status_code == 404

        await owner.post(f"/api/projects/{project['id']}/publish", headers=headers)
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as anon:
            res = await anon.get(asset["url"])
            assert res.status_code == 200
            assert res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_ai_plans_catalog_and_quota_follow_org_plan():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        _project, headers, _ = await _new_tenant(owner)

        plans = (await owner.get("/api/ai/plans", headers=headers)).json()
        assert {p["slug"] for p in plans} >= {"free", "pro", "enterprise"}

        usage = (await owner.get("/api/org/ai-usage", headers=headers)).json()
        assert usage["plan"] is None
        assert usage["monthly_token_limit"] == 200_000

        assigned = await owner.put("/api/org/plan", json={"plan_slug": "enterprise"}, headers=headers)
        assert assigned.status_code == 200, assigned.text
        usage = assigned.json()
        assert usage["plan"]["slug"] == "enterprise"
        assert usage["monthly_token_limit"] == 20_000_000

        unknown = await owner.put("/api/org/plan", json={"plan_slug": "nao-existe"}, headers=headers)
        assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_guest_comments_require_allow_comments_and_valid_screen():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        project, headers, _ = await _new_tenant(owner)
        screens = (await owner.get(f"/api/projects/{project['id']}/screens", headers=headers)).json()
        screen_id = screens[0]["id"]

        no_comments = (
            await owner.post(
                f"/api/projects/{project['id']}/share-links",
                json={"allow_comments": False},
                headers=headers,
            )
        ).json()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as guest:
            res = await guest.post(
                f"/api/public/p/{no_comments['slug']}/comments",
                json={"screen_id": screen_id, "body": "oi"},
            )
            assert res.status_code == 403

        link = (
            await owner.post(
                f"/api/projects/{project['id']}/share-links",
                json={"allow_comments": True},
                headers=headers,
            )
        ).json()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as guest:
            created = await guest.post(
                f"/api/public/p/{link['slug']}/comments",
                json={"screen_id": screen_id, "body": "Header precisa de ajuste", "guest_name": "CEO"},
            )
            assert created.status_code == 200, created.text
            assert created.json()["author_name"] == "CEO"

            listed = await guest.get(f"/api/public/p/{link['slug']}/comments?screen_id={screen_id}")
            assert listed.status_code == 200
            assert any(c["body"] == "Header precisa de ajuste" for c in listed.json())

            wrong_screen = await guest.post(
                f"/api/public/p/{link['slug']}/comments",
                json={"screen_id": "nao-existe", "body": "invalido"},
            )
            assert wrong_screen.status_code == 404


@pytest.mark.asyncio
async def test_websocket_presence_cursor_and_origin_check():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as owner:
        project, _headers, _ = await _new_tenant(owner)
        cookie = "; ".join(f"{k}={v}" for k, v in owner.cookies.items())

    headers = {"Cookie": cookie, "Origin": BASE_URL}
    url = f"{WS_URL}/api/ws/projects/{project['id']}"

    async with websockets.connect(url, additional_headers=headers) as first:
        ready = json.loads(await first.recv())
        if ready["type"] != "ready":
            ready = json.loads(await first.recv())
        assert ready["type"] == "ready"

        async with websockets.connect(url, additional_headers=headers) as second:
            # Presença chega ao primeiro participante
            presence = json.loads(await asyncio.wait_for(first.recv(), 5))
            if presence["type"] == "ready":
                presence = json.loads(await asyncio.wait_for(first.recv(), 5))
            assert presence["type"] == "presence"
            assert presence["participants"]

            await second.send(json.dumps({"type": "cursor", "screen_id": "s1", "x": 10, "y": 20}))
            cursor = json.loads(await asyncio.wait_for(first.recv(), 5))
            while cursor["type"] != "cursor":
                cursor = json.loads(await asyncio.wait_for(first.recv(), 5))
            assert cursor["x"] == 10

    with pytest.raises(Exception):
        async with websockets.connect(url, additional_headers={"Origin": "http://evil.example"}) as ws:
            await ws.recv()
