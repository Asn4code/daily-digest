"""Validated report screens and explicit, CSRF-protected human review actions."""

import json
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

from digest import notebook, planning, queue
from digest.config import Config
from digest.report.model import Report, ResultEntry
from digest.report.timeutil import display
from digest.report.views import CONFIDENCE, PRIORITIES, daily_view, weekly_checks, weekly_notices
from digest.review import records
from digest.review.select import select as select_review
from digest.util.fs import ReadError
from digest.web import jobs
from digest.web.notebook_graph import layout as notebook_layout
from digest.web.security import Security, form_values
from digest.web.store import Store

ENV = Environment(loader=PackageLoader("digest.web", "templates"), autoescape=select_autoescape())
ENV.filters.update(
    localtime=display, confidence=lambda v: CONFIDENCE[v], priority=lambda v: PRIORITIES[v]
)
ENV.filters["task_state"] = lambda v: {
    "proposed": "Propuesta",
    "todo": "Pendiente",
    "doing": "En curso",
    "review": "En revisión",
    "done": "Terminada",
    "archived": "Fuera de captura",
}.get(v, "No disponible")
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

    @app.get("/notebook", response_class=HTMLResponse)
    def notebook_page(
        request: Request,
        project: str = "",
        state: str = "open",
        q: str = "",
        minimum: int = 0,
        page_number: int = 1,
        view: str = "cards",
    ) -> HTMLResponse:
        if (
            project
            and project not in {p.id for p in config.projects}
            or state not in notebook.STATES | {"all", "open", "available", "blocked", "archived"}
            or len(q) > 200
            or not 0 <= minimum <= 100
            or not 1 <= page_number <= 10000
            or view not in {"cards", "graph"}
        ):
            raise HTTPException(400)
        try:
            with store.database() as db:
                db.execute("BEGIN")
                tasks, sources = notebook.catalogue(db, config)
        except (OSError, ReadError):
            tasks, sources = [], []
        except (ValueError, sqlite3.Error):
            raise HTTPException(409) from None
        selected = [
            t
            for t in tasks
            if (not project or t["project_id"] == project)
            and (
                state == "all"
                or state == "open"
                and t["state"] not in {"done", "archived"}
                or state == "available"
                and t["available"]
                or state == "blocked"
                and bool(t["blockers"])
                and t["state"] != "done"
                or state == t["state"]
            )
            and t["suggested"] >= minimum
            and (
                not q
                or q.casefold()
                in (
                    t["id"]
                    + " "
                    + t["title"]
                    + " "
                    + t["description"]
                    + " "
                    + t["personal"]["note"]
                ).casefold()
            )
        ]
        visible = selected[(page_number - 1) * 60 : page_number * 60]
        from urllib.parse import urlencode

        base = {"project": project, "state": state, "q": q, "minimum": minimum}
        return page(
            request,
            "notebook.html",
            title="Cuaderno personal",
            tasks=visible,
            sources=sources,
            projects=[{"id": p.id, "name": p.name} for p in config.projects],
            selected_project=project,
            state=state,
            query=q,
            minimum=minimum,
            view=view,
            total=len(selected),
            all_count=len(tasks),
            archived_count=sum(t["state"] == "archived" for t in tasks),
            page_number=page_number,
            graph=notebook_layout(visible),
            refresh_nonce=secrets.token_hex(16),
            cards_url="/notebook?"
            + urlencode({**base, "view": "cards", "page_number": page_number}),
            graph_url="/notebook?"
            + urlencode({**base, "view": "graph", "page_number": page_number}),
            previous_url="/notebook?"
            + urlencode({**base, "view": view, "page_number": page_number - 1})
            if page_number > 1
            else None,
            next_url="/notebook?"
            + urlencode({**base, "view": view, "page_number": page_number + 1})
            if len(selected) > page_number * 60
            else None,
        )

    @app.post("/notebook/refresh")
    async def refresh_notebook(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"submission_id"}:
            raise HTTPException(400)

        def save() -> int:
            try:
                with queue.writing(config) as db:
                    return queue.refresh_notebook(db, fields["submission_id"])
            except (OSError, ValueError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/jobs/{ident}", status_code=303)

    @app.get("/notebook/settings", response_class=HTMLResponse)
    def notebook_settings(request: Request) -> HTMLResponse:
        try:
            with store.database() as db:
                rule, revision = notebook.settings(db)
        except (OSError, ReadError):
            rule, revision = notebook.Settings(), None
        except (ValueError, sqlite3.Error):
            raise HTTPException(409) from None
        return page(
            request,
            "notebook_settings.html",
            title="Reglas de prioridad",
            rule=rule,
            expected=revision or "",
            submission_id=secrets.token_hex(16),
        )

    @app.post("/notebook/settings")
    async def update_notebook_settings(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {
            "base",
            "daily_step",
            "cap",
            "enabled",
            "expected",
            "submission_id",
        } or fields["enabled"] not in {"0", "1"}:
            raise HTTPException(400)

        def save() -> None:
            try:
                with queue.writing(config) as db:
                    notebook.save_settings(
                        db,
                        {
                            "base": int(fields["base"]),
                            "daily_step": int(fields["daily_step"]),
                            "cap": int(fields["cap"]),
                            "enabled": fields["enabled"] == "1",
                        },
                        fields["expected"] or None,
                        fields["submission_id"],
                    )
            except (OSError, ValueError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse("/notebook/settings", status_code=303)

    @app.get("/notebook/{project_id}/{task_id}", response_class=HTMLResponse)
    def notebook_task(
        request: Request,
        project_id: str,
        task_id: str,
        history_page: int = 1,
        evidence_page: int = 1,
    ) -> HTMLResponse:
        if not 1 <= evidence_page <= 10000:
            raise HTTPException(400)
        try:
            with store.database() as db:
                db.execute("BEGIN")
                item = notebook.task(db, config, project_id, task_id)
                versions, more = notebook.history(db, project_id, task_id, history_page)
                rows = db.execute(
                    "SELECT id,kind,locator,excerpt FROM evidence WHERE project_id=? AND task_id=? "
                    "ORDER BY observed_at DESC,id DESC LIMIT 51 OFFSET ?",
                    (project_id, task_id, (evidence_page - 1) * 50),
                ).fetchall()
                related = notebook.source(
                    db, config, next(p for p in config.projects if p.id == project_id)
                )
                dependents = [ident for ident, t in related.tasks.items() if task_id in t["deps"]]
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(404) from None
        return page(
            request,
            "notebook_task.html",
            title=item["title"],
            item=item,
            versions=versions,
            history_more=more,
            history_page=history_page,
            evidence=[
                {"id": r[0], "kind": r[1], "locator": r[2], "excerpt": r[3]} for r in rows[:50]
            ],
            evidence_more=len(rows) > 50,
            evidence_page=evidence_page,
            dependencies=[
                {
                    "id": ident,
                    "title": related.tasks.get(ident, {}).get("title"),
                    "state": related.tasks.get(ident, {}).get("state"),
                }
                for ident in item["deps"]
            ],
            dependents=dependents,
            submission_id=secrets.token_hex(16),
        )

    @app.post("/notebook/{project_id}/{task_id}")
    async def update_notebook_task(request: Request, project_id: str, task_id: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"base", "aging", "note", "expected", "submission_id"}:
            raise HTTPException(400)

        def save() -> None:
            try:
                values = {
                    "base": int(fields["base"]) if fields["base"] else None,
                    "aging": fields["aging"],
                    "note": fields["note"],
                }
                with queue.writing(config) as db:
                    notebook.save(
                        db,
                        config,
                        project_id,
                        task_id,
                        values,
                        fields["expected"],
                        fields["submission_id"],
                    )
            except (OSError, ValueError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse(f"/notebook/{project_id}/{task_id}", status_code=303)

    @app.get("/generate", response_class=HTMLResponse)
    def generate_page(request: Request, page_number: int = 1) -> HTMLResponse:
        try:
            state = jobs.board(store, page_number)
        except ValueError:
            raise HTTPException(400) from None
        return page(
            request,
            "generate.html",
            title="Generar",
            board=state,
            submission_ids={k: secrets.token_hex(16) for k in queue.REPORT_KINDS},
            signature=jobs.signature(state),
        )

    @app.get("/generate/status")
    def generate_status(page_number: int = 1) -> JSONResponse:
        try:
            return JSONResponse({"signature": jobs.signature(jobs.board(store, page_number))})
        except ValueError:
            raise HTTPException(400) from None

    @app.post("/generate")
    async def generate_report(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"kind", "submission_id"}:
            raise HTTPException(400)

        def save() -> int:
            try:
                with queue.writing(config) as db:
                    return queue.generate(db, fields["kind"], fields["submission_id"])
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/jobs/{ident}", status_code=303)

    def job_state(job_id: int, page_number: int = 1) -> dict[str, Any]:
        try:
            return jobs.detail(store, config, job_id, page_number)
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(404) from None

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: int, page_number: int = 1) -> HTMLResponse:
        state = job_state(job_id, page_number)
        return page(
            request,
            "job.html",
            title="Estado del trabajo",
            job=state,
            submission_id=secrets.token_hex(16),
            submission_ids={str(d["id"]): secrets.token_hex(16) for d in state["deliveries"]},
            signature=jobs.signature(state),
        )

    @app.get("/jobs/{job_id}/status")
    def job_status(job_id: int, page_number: int = 1) -> JSONResponse:
        state = job_state(job_id, page_number)
        return JSONResponse({"signature": jobs.signature(state), "state": state["state"]})

    @app.post("/jobs/{job_id}/resume")
    async def resume_job(request: Request, job_id: int) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"submission_id"}:
            raise HTTPException(400)

        def save() -> int:
            try:
                with queue.writing(config) as db:
                    return queue.resume(db, job_id, fields["submission_id"])
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        await run_in_threadpool(save)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/deliveries/{delivery_id}/retry")
    async def retry_delivery(request: Request, delivery_id: int) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"submission_id"}:
            raise HTTPException(400)

        def save() -> int:
            try:
                with queue.writing(config) as db:
                    return queue.retry_delivery(db, delivery_id, fields["submission_id"])
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/jobs/{ident}", status_code=303)

    @app.post("/plans/{plan_id}/deliveries/{channel}/retry")
    async def retry_plan_delivery(request: Request, plan_id: str, channel: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {"submission_id"}:
            raise HTTPException(400)

        def save() -> int:
            try:
                with queue.writing(config) as db:
                    return queue.retry_plan(db, config, plan_id, channel, fields["submission_id"])
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/jobs/{ident}", status_code=303)

    @app.get("/plan", response_class=HTMLResponse)
    def current_plan(request: Request) -> Response:
        ident = store.select("daily")
        return (
            RedirectResponse(f"/reports/{ident}/plan", status_code=303)
            if ident
            else page(request, "empty.html", title="Plan")
        )

    @app.get("/plan/{date}")
    def dated_plan(date: str) -> Response:
        ident = store.select("daily", date)
        if ident is None:
            raise HTTPException(404)
        return RedirectResponse(f"/reports/{ident}/plan", status_code=303)

    @app.get("/reports/{report_id}/plan", response_class=HTMLResponse)
    def plan_page(request: Request, report_id: str) -> HTMLResponse:
        document, _ = report(report_id)
        try:
            with store.database() as db:
                entries = planning.items(db, document)
                selected = planning.active(db, config)
                expected = planning.token(db, config, document)
                doubts = db.execute(
                    "SELECT v.id,v.result_id,v.doubts FROM review v "
                    "JOIN result r ON r.id=v.result_id "
                    "WHERE v.doubts!='[]' AND v.id=(SELECT latest.id FROM review latest "
                    "WHERE latest.result_id=v.result_id "
                    "ORDER BY submitted_at DESC,id DESC LIMIT 1) "
                    "ORDER BY v.submitted_at DESC,v.id DESC LIMIT 40"
                ).fetchall()
                last = db.execute(
                    "SELECT value FROM meta WHERE key LIKE 'plan_snapshot:%' "
                    "ORDER BY json_extract(value,'$.created_at') DESC,key DESC LIMIT 1"
                ).fetchone()
        except (ValueError, OSError, sqlite3.Error):
            raise HTTPException(409) from None
        weekly_id = store.select("weekly")
        weekly = report(weekly_id)[0] if weekly_id else None

        return page(
            request,
            "plan.html",
            title="Próximo foco",
            report=document,
            entries=entries,
            selected=selected,
            expected=expected,
            submission_ids={i["id"]: secrets.token_hex(16) for i in entries},
            view=daily_view(document),
            doubts=[{"id": r[0], "result_id": r[1], "text": json.loads(r[2])} for r in doubts],
            weekly=weekly,
            critical=weekly_checks(weekly)[:3] if weekly else [],
            latest=json.loads(last[0]) if last else None,
        )

    @app.post("/reports/{report_id}/plan")
    async def update_plan(request: Request, report_id: str) -> Response:
        from starlette.concurrency import run_in_threadpool

        fields = await form(request)
        if set(fields) != {
            "item_id",
            "decision",
            "action",
            "done_criterion",
            "dependency",
            "expected",
            "submission_id",
        }:
            raise HTTPException(400)

        def save() -> str:
            try:
                with records.writing(config) as db:
                    return planning.decide(
                        db,
                        config,
                        report_id,
                        int(fields["item_id"]),
                        fields["decision"],
                        {k: fields[k] for k in ("action", "done_criterion", "dependency")},
                        fields["expected"],
                        fields["submission_id"],
                    )
            except (ValueError, OSError, sqlite3.Error):
                raise HTTPException(409) from None

        ident = await run_in_threadpool(save)
        return RedirectResponse(f"/plans/{ident}", status_code=303)

    @app.post("/plan/{date}")
    async def update_dated_plan(request: Request, date: str) -> Response:
        ident = store.select("daily", date)
        if ident is None:
            raise HTTPException(404)
        return await update_plan(request, ident)

    @app.get("/plans/{snapshot_id}", response_class=HTMLResponse)
    def plan_snapshot(request: Request, snapshot_id: str) -> HTMLResponse:
        try:
            with store.database() as db:
                value = planning.snapshot(db, config, snapshot_id)
                deliveries = {
                    name: planning.meta(
                        db, f"plan_delivery:{snapshot_id}:{name}", {"state": "pending"}
                    )
                    for name in ("obsidian", "drive")
                }
        except (OSError, ValueError, sqlite3.Error):
            raise HTTPException(404) from None
        return page(
            request,
            "plan_snapshot.html",
            title="Tu decisión de foco",
            snapshot=value,
            deliveries=deliveries,
        )

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
