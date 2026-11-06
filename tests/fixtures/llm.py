"""Deterministic schema-valid responses for worker and publication tests."""

import html
import json
import re

import httpx


def fake_response(request: httpx.Request) -> httpx.Response:
    wire = json.loads(request.content)
    text = wire["messages"][1]["content"]
    package = json.loads(html.unescape(re.search(r"<context>(.*?)</context>", text, re.S).group(1)))
    entries = [
        json.loads(html.unescape(raw))
        for raw in re.findall(r'<evidence id="[^"]+">(.*?)</evidence>', text, re.S)
    ]
    eid = entries[0]["id"]
    claim = {"text": "Hay evidencia disponible para contrastar.", "evidence": [eid]}
    title = wire["response_format"]["json_schema"]["schema"]["title"]
    if title == "ResultExtraction":
        value = {
            "result_id": package["context"]["result_id"],
            "summary": claim["text"],
            "facts": [claim],
            "numbers": [],
            "interpretations": [],
            "uncertainties": [],
            "controls_and_parameters": [],
            "failures_or_blockers": [],
            "open_threads": [],
        }
    elif title == "DailySynthesis":
        value = {
            "highlights": [claim],
            "projects": [
                {
                    "project_id": pid,
                    "known_now": [claim],
                    "still_unknown": ["Falta contrastar la interpretación."],
                    "decisions_changed": [],
                    "no_new_conclusion": True,
                }
                for pid in package["project_ids"]
            ],
            "review_candidate": None,
        }
    elif title == "TomorrowPlan":
        value = {
            "mission": {
                "kind": "mission",
                "action": "Contrastar el resultado con un control",
                "done_criterion": "Explicación contrastada con las evidencias",
                "dependency": None,
                "reason": claim["text"],
                "origin": "model",
                "kanvas_task_id": None,
                "evidence": [eid],
            },
            "warmups": [],
        }
    elif title == "WeeklyReport":
        objective = {
            "kind": "mission",
            "action": "Contrastar el resultado con un control",
            "done_criterion": "Interpretación respaldada",
            "dependency": None,
            "reason": claim["text"],
            "origin": "model",
            "kanvas_task_id": None,
            "evidence": [eid],
        }
        value = {
            "projects": [
                {
                    "project_id": pid,
                    "progress_vs_objective": [claim],
                    "decisions": [],
                    "hypotheses_changed": [],
                }
                for pid in package["project_ids"]
            ],
            "patterns": [claim],
            "key_figures": [e["id"] for e in entries if e["kind"] == "figure"][:6],
            "review_status": {
                "completed": package["completed_reviews"],
                "pending": package["pending_reviews"],
                "doubts": [],
            },
            "next_week": [objective, objective, {**objective, "action": "Sesión de revisión"}],
        }
    else:
        raise AssertionError(title)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
