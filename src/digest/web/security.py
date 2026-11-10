"""Loopback access, authenticated sessions and bounded CSRF-protected requests."""

import hashlib
import hmac
import ipaddress
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from digest.config import WebConfig

SESSION_COOKIE = "digest_session"
MAX_FORM_BYTES = 64_000
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def form_values(body: bytes) -> dict[str, list[str]]:
    """Decode a bounded form without accepting replacement characters."""
    if len(body) > MAX_FORM_BYTES:
        raise ValueError("Form too large")
    return parse_qs(
        body.decode("utf-8"), keep_blank_values=True, errors="strict", max_num_fields=64
    )


class Security:
    def __init__(self, app: ASGIApp, config: WebConfig) -> None:
        self.app = app
        self.config = config
        self.key = secrets.token_bytes(32)
        public = urlsplit(config.public_base_url)
        if (
            public.scheme not in {"http", "https"}
            or not public.hostname
            or public.username is not None
            or public.password is not None
            or public.query
            or public.fragment
        ):
            raise ValueError("Invalid web public URL")
        self.public_origin = f"{public.scheme}://{public.netloc}"
        self.public_host = public.hostname
        self.hosts = {"127.0.0.1", "localhost", "::1", public.hostname}

    def digest(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def session(self, value: str) -> str | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}\.[a-f0-9]{64}", value):
            return None
        nonce, signature = value.split(".")
        return nonce if hmac.compare_digest(signature, self.digest(nonce)) else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)

        async def protected(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    (key.encode(), value.encode())
                    for key, value in {
                        "content-security-policy": CSP,
                        "x-content-type-options": "nosniff",
                        "referrer-policy": "no-referrer",
                        "x-frame-options": "DENY",
                        "cache-control": "no-store",
                    }.items()
                )
                if cookie:
                    headers.extend(cookie.raw_headers)
                message = {**message, "headers": headers}
            await send(message)

        cookie: Response | None = None

        async def deny(code: int) -> None:
            await HTMLResponse("Solicitud no autorizada o no válida.", status_code=code)(
                scope, receive, protected
            )

        try:
            peer = ipaddress.ip_address(request.client.host) if request.client else None
            authorities = request.headers.getlist("host")
            authority = urlsplit("http://" + authorities[0]) if len(authorities) == 1 else None
            if not peer or not peer.is_loopback or authority is None:
                await deny(403)
                return
            if (
                authority.hostname not in self.hosts
                or authority.username is not None
                or authority.password is not None
                or authority.path
                or authority.query
                or authority.fragment
            ):
                await deny(400)
                return
            _ = authority.port
        except ValueError:
            await deny(400)
            return
        identities = request.headers.getlist("tailscale-user-login")
        if identities and identities != [self.config.allowed_tailscale_login]:
            await deny(403)
            return

        nonce = self.session(request.cookies.get(SESSION_COOKIE, ""))
        valid_session = nonce is not None
        if nonce is None:
            nonce = secrets.token_urlsafe(32)
        csrf = self.digest("csrf:" + nonce)
        scope.setdefault("state", {}).update(csrf_token=csrf, session_id=nonce)
        replay_body: bytes | None = None
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not valid_session or request.headers.get("sec-fetch-site") == "cross-site":
                await deny(403)
                return
            expected_origin = (
                self.public_origin
                if identities
                else f"{request.url.scheme}://{request.headers['host']}"
            )
            if request.headers.get("origin", expected_origin) != expected_origin:
                await deny(403)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    await deny(400)
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_FORM_BYTES:
                    await deny(413)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            replay_body = bytes(body)
            tokens = request.headers.getlist("x-csrf-token")
            if not tokens:
                if request.headers.get("content-type", "").split(";", 1)[0] != (
                    "application/x-www-form-urlencoded"
                ):
                    await deny(403)
                    return
                try:
                    tokens = form_values(replay_body).get("csrf_token", [])
                except (ValueError, UnicodeError):
                    await deny(400)
                    return
            if len(tokens) != 1 or not re.fullmatch(r"[a-f0-9]{64}", tokens[0]):
                await deny(403)
                return
            if not hmac.compare_digest(tokens[0], csrf):
                await deny(403)
                return
        if not valid_session:
            cookie = Response()
            cookie.raw_headers = []
            cookie.set_cookie(
                SESSION_COOKIE,
                nonce + "." + self.digest(nonce),
                httponly=True,
                secure=request.url.scheme == "https"
                or (
                    self.config.public_base_url.startswith("https:")
                    and authority.hostname == self.public_host
                    and self.public_host not in {"localhost", "127.0.0.1", "::1"}
                ),
                samesite="strict",
                path="/",
            )

        async def replay() -> Message:
            nonlocal replay_body
            if replay_body is not None:
                chunk, replay_body = replay_body, None
                return {"type": "http.request", "body": chunk, "more_body": False}
            return await receive()

        await self.app(scope, replay, protected)
