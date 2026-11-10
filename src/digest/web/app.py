"""Validated report screens and explicit, CSRF-protected human review actions."""

import re
import secrets
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from digest.config import Config
from digest.report.model import Report, ResultEntry
from digest.report.timeutil import display
from digest.report.views import CONFIDENCE, PRIORITIES, daily_view, weekly_checks, weekly_notices
from digest.review import records
from digest.review.select import select as select_review
from digest.web.security import Security, form_values
from digest.web.store import Store

ENV = Environment(loader=PackageLoader("digest.web", "templates"), autoescape=select_autoescape())
ENV.filters.update(
    localtime=display, confidence=lambda v: CONFIDENCE[v], priority=lambda v: PRIORITIES[v]
)
ASSETS = {
    "app.css": "text/css",
    "app.js": "text/javascript",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}


def create_app(config: Config) -> FastAPI:
    config = config.model_copy(deep=True)
    store = Store(config)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    app.state.store = store
    app.add_middleware(Security, config=config.web)

    def page(request: Request, template: str, **context: Any) -> HTMLResponse:
        return HTMLResponse(
            ENV.get_template(template).render(
                request=request,
                csrf_token=request.state.csrf_token,
                timezone=config.timezone,
                **context,
            )
        )

    def report(ident: str) -> tuple[Report, Path]:
        try:
            return store.load(ident)
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(404) from None

    @app.exception_handler(HTTPException)
    async def error(request: Request, exc: HTTPException) -> HTMLResponse:
        response = page(request, "error.html", title="No disponible", status=exc.status_code)
        response.status_code = exc.status_code
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        ident = store.select("daily")
        if ident is None:
            return page(request, "empty.html", title="Hoy")
        return RedirectResponse("/reports/" + ident, status_code=303)

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    def show(request: Request, report_id: str) -> HTMLResponse:
        document, _ = report(report_id)
        with store.database() as db:
            chosen = select_review(db, document)
            corrections = records.corrections(db, config, document.id)
        return page(
            request,
            "report.html",
            title="Informe " + document.kind_label,
            report=document,
            view=daily_view(document),
            critical=weekly_checks(document),
            notices=weekly_notices(document),
            states=store.states(document),
            chosen=chosen,
            corrections=corrections,
        )

    @app.get("/r/{date}", response_class=HTMLResponse)
    def by_date(date: str) -> Response:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise HTTPException(404)
        ident = store.select("daily", date)
        if ident is None:
            raise HTTPException(404)
        return RedirectResponse("/reports/" + ident, status_code=303)

    @app.get("/week", response_class=HTMLResponse)
    def week(request: Request) -> Response:
        ident = store.select("weekly")
        return (
            RedirectResponse("/reports/" + ident, status_code=303)
            if ident
            else page(request, "empty.html", title="Semana")
        )

    @app.get("/w/{week}", response_class=HTMLResponse)
    def by_week(week: str) -> Response:
        if not re.fullmatch(r"\d{4}-W\d{2}", week):
            raise HTTPException(404)
        ident = store.select("weekly", week)
        if ident is None:
            raise HTTPException(404)
        return RedirectResponse("/reports/" + ident, status_code=303)

    @app.get("/reports/{report_id}/results/{result_id}", response_class=HTMLResponse)
    def detail(request: Request, report_id: str, result_id: str) -> HTMLResponse:
        document, _ = report(report_id)
        item = next((r for r in document.results if r.id == result_id), None)
        if item is None:
            raise HTTPException(404)
        with store.database() as db:
            corrections = [
                (ident, rid)
                for ident, rid in records.corrections(db, config, report_id)
                if rid == result_id
            ]
        return page(
            request,
            "result.html",
            title=item.title,
            report=document,
            item=item,
            view=daily_view(document),
            states=store.states(document),
            corrections=corrections,
        )

    @app.get("/r/{date}/res/{result_id}", response_class=HTMLResponse)
    def legacy_detail(date: str, result_id: str) -> Response:
        ident = store.select("daily", date)
        if ident is None:
            raise HTTPException(404)
        document, _ = report(ident)
        if result_id not in {r.id for r in document.results}:
            raise HTTPException(404)
        return RedirectResponse(f"/reports/{ident}/results/{result_id}", status_code=303)

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, q: str = "", page_number: str = "1") -> HTMLResponse:
        try:
            entries, more, truncated = store.catalogue(q, int(page_number))
        except ValueError:
            raise HTTPException(400) from None
        return page(
            request,
            "history.html",
            title="Historial",
            entries=entries,
            more=more,
            query=q,
            number=int(page_number),
            truncated=truncated,
        )

    @app.get("/reports/{report_id}/figures/{evidence_id}.png")
    def figure(report_id: str, evidence_id: str) -> Response:
        try:
            raw = store.figure(report_id, evidence_id)
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(404) from None
        return Response(raw, media_type="image/png")

    @app.get("/static/{name}")
    def asset(name: str) -> Response:
        if name not in ASSETS:
            raise HTTPException(404)
        return Response(
            files("digest.web").joinpath("static/" + name).read_bytes(), media_type=ASSETS[name]
        )

    @app.get("/manifest.webmanifest")
    def manifest() -> Response:
        raw = files("digest.web").joinpath("static/manifest.webmanifest").read_bytes()
        return Response(raw, media_type="application/manifest+json")

    @app.get("/healthz")
    def health() -> JSONResponse:
        try:
            with store.database() as db:
                db.execute("SELECT id FROM report LIMIT 1").fetchone()
        except (OSError, ValueError, sqlite3.Error):
            return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok", "database": "ok"})

    def review_record(review_id: str) -> tuple[dict[str, Any], Report]:
        try:
            with store.database() as db:
                return records.read(db, config, review_id)
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(404) from None

    @app.get("/review/{result_id}", response_class=HTMLResponse)
    def review_form(
        request: Request, result_id: str, report_id: str, mode: str = "short"
    ) -> Response:
        if mode not in records.FIELDS:
            raise HTTPException(400)
        document, _ = report(report_id)
        try:
            result = records.item(document, result_id)
        except ValueError:
            raise HTTPException(404) from None
        with store.database() as db:
            opened = records.open_review(db, result_id)
        if opened:
            return RedirectResponse(f"/review/{opened}/result", status_code=303)
        return page(
            request,
            "review.html",
            title="Tu explicación",
            report=document,
            item=result,
            mode=mode,
            fields=records.FIELDS[mode],
            submission_id=secrets.token_hex(16),
        )

    async def form(request: Request) -> dict[str, str]:
        try:
            fields = form_values(await request.body())
            if any(len(v) != 1 for v in fields.values()):
                raise ValueError("Repeated form fields")
            return {k: v[0] for k, v in fields.items() if k != "csrf_token"}
        except (UnicodeError, ValueError):
            raise HTTPException(400) from None

    @app.post("/review/{result_id}/submit")
    async def submit_review(request: Request, result_id: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        report_id = fields.pop("report_id", "")
        mode = fields.pop("mode", "")
        submission_id = fields.pop("submission_id", "")
        action = fields.pop("action", "submit")
        if action not in {"submit", "postpone"} or action == "postpone" and mode != "minimal":
            raise HTTPException(400)

        def save() -> str:
            try:
                with records.writing(config) as db:
                    return records.submit(
                        db,
                        config,
                        report_id,
                        result_id,
                        mode,
                        fields,
                        postpone=action == "postpone",
                        submission_id=submission_id,
                    )
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/review/{ident}/result", status_code=303)

    @app.get("/review/{review_id}/result", response_class=HTMLResponse)
    def review_result(request: Request, review_id: str) -> HTMLResponse:
        record, document = review_record(review_id)
        with store.database() as db:
            job = db.execute(
                "SELECT id,state FROM job WHERE kind='contrast' "
                "AND json_extract(params,'$.review')=? "
                "ORDER BY id DESC LIMIT 1",
                (review_id,),
            ).fetchone()
        return page(
            request,
            "contrast.html",
            title="Contraste de tu explicación",
            review=record,
            report=document,
            item=records.item(document, record["result_id"]),
            fields=records.FIELDS[record["mode"]],
            view=daily_view(document),
            job=job,
        )

    @app.post("/review/{review_id}/decide")
    async def decide_review(request: Request, review_id: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"decision", "doubt"}:
            raise HTTPException(400)

        def save() -> None:
            try:
                with records.writing(config) as db:
                    records.decide(db, config, review_id, fields["decision"], fields["doubt"])
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse(f"/review/{review_id}/result", status_code=303)

    @app.get("/review/{review_id}/status")
    def review_status(review_id: str) -> JSONResponse:
        record, _ = review_record(review_id)
        with store.database() as db:
            job = db.execute(
                "SELECT state FROM job WHERE kind='contrast' AND json_extract(params,'$.review')=? "
                "ORDER BY id DESC LIMIT 1",
                (review_id,),
            ).fetchone()
        state = (
            "decided"
            if record["decision"]
            else "ready"
            if record["contrast"]
            else "failed"
            if job and job[0] == "failed"
            else "pending"
        )
        return JSONResponse({"state": state})

    @app.post("/review/{review_id}/retry")
    async def retry_review(request: Request, review_id: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        if await form(request):
            raise HTTPException(400)

        def save() -> None:
            try:
                with records.writing(config) as db:
                    records.retry(db, config, review_id)
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse(f"/review/{review_id}/result", status_code=303)

    return app


def review_label(state: str) -> str:
    return ResultEntry("", "", "", None, state, []).review_label


ENV.globals["review_label"] = review_label
