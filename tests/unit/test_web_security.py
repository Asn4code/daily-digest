"""Browser-compatible forms retain strict origin, session and CSRF checks."""

import asyncio

import httpx
from fastapi import FastAPI, Request

from digest.config import WebConfig
from digest.web.security import Security


def app(port=8091, public="https://digest.example.ts.net"):
    application = FastAPI()
    application.add_middleware(
        Security,
        config=WebConfig(
            port=port, public_base_url=public, allowed_tailscale_login="test@example.org"
        ),
    )

    @application.get("/")
    def token(request: Request):
        return {"token": request.state.csrf_token}

    @application.post("/")
    def action():
        return {"saved": True}

    return application


def test_T20_same_origin_policy_keeps_browser_forms_and_origin_checks_compatible():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app(), client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1:8091",
        ) as client:
            page = await client.get("/")
            assert page.headers["referrer-policy"] == "same-origin"
            token = page.json()["token"]
            assert "HttpOnly" in page.headers["set-cookie"]
            assert "SameSite=strict" in page.headers["set-cookie"]
            for origin in ("null", "https://evil.example", "http://127.0.0.1:8090"):
                response = await client.post(
                    "/",
                    data={"csrf_token": token},
                    headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
                )
                assert response.status_code == 403
            headers = {"Origin": "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin"}
            assert (
                await client.post("/", data={"csrf_token": token}, headers=headers)
            ).status_code == 200
            assert (
                await client.post("/", data={"csrf_token": "a" * 64}, headers=headers)
            ).status_code == 403
            assert (
                await client.post(
                    "/",
                    data={"csrf_token": token},
                    headers={**headers, "Sec-Fetch-Site": "cross-site"},
                )
            ).status_code == 403

    asyncio.run(run())


def test_local_instances_on_different_ports_do_not_replace_each_others_cookies():
    async def run():
        first = httpx.ASGITransport(app(8091), client=("127.0.0.1", 50000))
        second = httpx.ASGITransport(app(8090), client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=first, base_url="http://127.0.0.1:8091") as a:
            initial = await a.get("/")
            token = initial.json()["token"]
            async with httpx.AsyncClient(transport=second, base_url="http://127.0.0.1:8090") as b:
                b.cookies.update(a.cookies)
                other = await b.get("/")
                assert (
                    initial.headers["set-cookie"].split("=", 1)[0]
                    != other.headers["set-cookie"].split("=", 1)[0]
                )
                a.cookies.update(b.cookies)
                assert (
                    await a.post(
                        "/", data={"csrf_token": token}, headers={"Origin": "http://127.0.0.1:8091"}
                    )
                ).status_code == 200
                assert (await b.post("/", data={"csrf_token": token})).status_code == 403

    asyncio.run(run())


def test_T19_private_https_identity_and_secure_cookie_remain_required():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app(), client=("127.0.0.1", 50000)),
            base_url="https://digest.example.ts.net",
        ) as client:
            identity = {"Tailscale-User-Login": "test@example.org"}
            page = await client.get("/", headers=identity)
            assert "Secure" in page.headers["set-cookie"]
            token = page.json()["token"]
            assert (
                await client.post(
                    "/",
                    data={"csrf_token": token},
                    headers={**identity, "Origin": "https://digest.example.ts.net"},
                )
            ).status_code == 200
            assert (
                await client.post(
                    "/", data={"csrf_token": token}, headers={**identity, "Origin": "null"}
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/",
                    data={"csrf_token": token},
                    headers={
                        "Tailscale-User-Login": "other@example.org",
                        "Origin": "https://digest.example.ts.net",
                    },
                )
            ).status_code == 403

    asyncio.run(run())
