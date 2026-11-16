"""Human monitoring input and history, protected by the application's middleware."""

import json
import secrets
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, RedirectResponse, Response

from digest import queue, watchlist
from digest.collectors.base import canonical, content_hash
from digest.config import Config
from digest.util.fs import ReadError
from digest.util.redact import known_secrets, redact_tree
from digest.web.store import Store


def install(
    app: FastAPI,
    config: Config,
    store: Store,
    page: Callable[..., HTMLResponse],
    form: Callable[[Request], Awaitable[dict[str, str]]],
) -> None:
    def context() -> dict[str, Any]:
        return {
            "title": "Seguimiento",
            "projects": [{"id": p.id, "name": p.name} for p in config.projects],
            "states": watchlist.STATES,
            "submission_id": secrets.token_hex(16),
        }

    @app.get("/watchlist", response_class=HTMLResponse)
    def index(request: Request, page_number: int = 1) -> HTMLResponse:
        if not 1 <= page_number <= 10000:
            raise HTTPException(400)
        try:
            with store.database() as db:
                db.execute("BEGIN")
                items = watchlist.catalogue(db)
                etag = watchlist.expected(db)
        except (OSError, ReadError):
            items, etag = [], content_hash(canonical([]))
        except (ValueError, sqlite3.Error):
            raise HTTPException(409) from None
        start = (page_number - 1) * 30
        return page(
            request,
            "watchlist.html",
            **context(),
            items=redact_tree(items[start : start + 30], known_secrets(config)),
            expected=etag,
            page_number=page_number,
            more=len(items) > start + 30,
            active=sum(s["values"]["state"] == "active" for s in items),
        )

    @app.post("/watchlist/preview", response_class=HTMLResponse)
    async def preview(request: Request) -> HTMLResponse:
        fields = await form(request)
        if set(fields) != {"text", "projects", "priority", "expected", "submission_id"}:
            raise HTTPException(400)
        try:
            values = watchlist.draft(
                fields["text"],
                [p.strip() for p in fields["projects"].split(",") if p.strip()],
                int(fields["priority"]),
            )
            if any(not set(v["projects"]) <= {p.id for p in config.projects} for v in values):
                raise ValueError("Unknown project")
        except ValueError:
            raise HTTPException(400) from None
        values = redact_tree(values, known_secrets(config))
        return page(
            request,
            "watchlist_preview.html",
            **context(),
            values=values,
            draft=json.dumps(values, ensure_ascii=False),
            expected=fields["expected"],
        )

    @app.post("/watchlist/save")
    async def add(request: Request) -> Response:
        fields = await form(request)
        if set(fields) != {"draft", "expected", "submission_id"}:
            raise HTTPException(400)

        def save() -> None:
            try:
                values = json.loads(fields["draft"])
                if not isinstance(values, list):
                    raise ValueError("Invalid list")
                with queue.writing(config) as db:
                    watchlist.save(db, config, values, fields["expected"], fields["submission_id"])
            except (ValueError, TypeError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse("/watchlist", status_code=303)

    @app.get("/watchlist/{item_id}", response_class=HTMLResponse)
    def detail(request: Request, item_id: str, history_page: int = 1) -> HTMLResponse:
        try:
            with store.database() as db:
                db.execute("BEGIN")
                item = next(s for s in watchlist.catalogue(db) if s["item_id"] == item_id)
                versions, more = watchlist.history(db, item_id, history_page)
                etag = watchlist.expected(db)
                reports = db.execute(
                    "SELECT r.id,i.end_at FROM report r JOIN interval i ON i.id=r.interval_id "
                    "WHERE r.status='ready' AND EXISTS (SELECT 1 FROM meta m "
                    "WHERE m.key='wl_report:'||r.id||':'||?) "
                    "ORDER BY i.end_at DESC,r.revision DESC LIMIT 20",
                    (item_id,),
                ).fetchall()
        except (StopIteration, ValueError, OSError, sqlite3.Error):
            raise HTTPException(404) from None
        return page(
            request,
            "watchlist_item.html",
            **context(),
            item=redact_tree(item, known_secrets(config)),
            versions=redact_tree(versions, known_secrets(config)),
            expected=etag,
            history_page=history_page,
            more=more,
            reports=reports,
        )

    @app.post("/watchlist/{item_id}")
    async def edit(request: Request, item_id: str) -> Response:
        fields = await form(request)
        if set(fields) != {
            "title",
            "question",
            "projects",
            "priority",
            "state",
            "expected",
            "submission_id",
        }:
            raise HTTPException(400)

        def save() -> None:
            try:
                values = {
                    "title": fields["title"],
                    "question": fields["question"],
                    "projects": [p.strip() for p in fields["projects"].split(",") if p.strip()],
                    "priority": int(fields["priority"]),
                    "state": fields["state"],
                }
                with queue.writing(config) as db:
                    watchlist.save(
                        db,
                        config,
                        [values],
                        fields["expected"],
                        fields["submission_id"],
                        item_id=item_id,
                    )
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse("/watchlist/" + item_id, status_code=303)
