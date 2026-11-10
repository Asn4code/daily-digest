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
    eid = next(
        (
            e["id"]
            for e in entries
            if e.get("meta", {}).get("capture_origin") == "observed_change"
            or (e.get("event_at") and e.get("meta", {}).get("report_role") == "interval_evidence")
        ),
        entries[0]["id"],
    )
    claim = {"text": "Hay evidencia disponible para contrastar.", "evidence": [eid]}
    title = wire["response_format"]["json_schema"]["schema"]["title"]
    if title == "GroundingAudit":
        value = {"approved": True, "issues": []}
    elif title == "Contrast":
        value = {
            "supported": [claim],
            "omissions": [],
            "unsupported": [],
            "unverifiable": [],
            "summary_errors": [],
        }
    elif title == "SourceFindings":
        value = {
            "result_id": package["context"]["result_id"],
            "summary": claim,
            "observations": [claim],
            "interpretations": [],
            "controls": [],
            "limitations": [],
            "open_questions": [],
        }
    elif title == "ResultExtraction":
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
    elif title == "ProjectDigest":
        cards = []
        for rid in package["context"]["fiches"]:
            refs = package["result_evidence"][rid][:1]
            local = {"text": claim["text"], "evidence": refs}
            cards.append(
                {
                    "result_id": rid,
                    "question": None,
                    "observations": [local],
                    "meaning": None,
                    "controls": [],
                    "limits": [{"text": "Falta contrastar la interpretación.", "evidence": refs}],
                    "decision_impact": None,
                    "next_question": None,
                }
            )
        eid = next(ids[0] for ids in package["result_evidence"].values() if ids)
        claim = {**claim, "evidence": [eid]}
        value = {
            "project_id": package["context"]["project_id"],
            "explanation": claim,
            "importance": {**claim, "confidence": "low"},
            "known_now": [claim],
            "still_unknown": [{"text": "Falta contrastar la interpretación.", "evidence": [eid]}],
            "decisions_changed": [],
            "no_new_conclusion": True,
            "reading_conditions": [
                {"text": "Falta contrastar la interpretación.", "evidence": [eid]}
            ],
            "results": cards,
        }
    elif title == "DailyOverview":
        pid = package["project_ids"][0]
        observation = package["context"]["balances"][pid]["known_now"][0]
        rid = next(
            rid
            for rid, ids in package["result_evidence"].items()
            if package["result_projects"][rid] == pid and set(ids) & set(observation["evidence"])
        )
        value = {
            "highlights": [
                {
                    "project_id": pid,
                    "result_ids": [rid],
                    "observation": observation,
                    "meaning": {**observation, "confidence": "low"},
                    "decisive_limit": {
                        "text": "Falta contrastar la interpretación.",
                        "evidence": observation["evidence"],
                    },
                }
            ],
            "review_candidate": None,
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
        accepted = package["active_plan_id"]
        value = {
            "mission": None
            if accepted is not None
            else {
                "kind": "mission",
                "project_id": package["project_ids"][0],
                "action": "Contrastar el resultado con un control",
                "done_criterion": "Explicación contrastada con las evidencias",
                "dependency": None,
                "reason": claim["text"],
                "origin": "model",
                "kanvas_task_id": None,
                "evidence": [eid],
                "priority_basis": ["control"],
                "decision_unlocked": "Decidir qué interpretación sostener",
                "uncertainty_addressed": {
                    "text": "Falta contrastar la interpretación.",
                    "evidence": [eid],
                },
                "human_plan_id": None,
            },
            "warmups": [],
            "carry_forward_id": accepted,
            "change_reason": None,
            "no_mission_reason": None,
        }
    elif title == "WeeklyCritical":
        value = {
            "project_id": package["context"]["project_id"],
            "progress_vs_objective": [claim],
            "decisions": [],
            "hypotheses_changed": [],
            "checks": [],
            "no_comparison_reason": claim,
        }
        for cid, prior in package["conclusions"].items():
            refs = list(dict.fromkeys(prior["evidence"][:1] + prior["new_evidence"][:1]))
            pair = {"text": "El contraste requiere comprobar condiciones.", "evidence": refs}
            value["checks"].append(
                {
                    "conclusion_id": cid,
                    "new_evidence": prior["new_evidence"][:1],
                    "outcome": "inconclusive",
                    "comparable": False,
                    "comparability": pair,
                    "assessment": {**pair, "confidence": "low"},
                    "decisive_limit": pair,
                    "alternative_explanations": [],
                    "analyses": [],
                    "focus_implication": pair,
                }
            )
        if value["checks"]:
            value["no_comparison_reason"] = None
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
            "project_id": package["project_ids"][0],
            "critical_ids": [],
        }
        value = {
            "projects": [
                {
                    field: package["context"]["project_balances"][pid][field]
                    for field in (
                        "project_id",
                        "progress_vs_objective",
                        "decisions",
                        "hypotheses_changed",
                    )
                }
                for pid in package["context"]["project_balances"]
            ],
            "patterns": [claim],
            "key_figures": [e["id"] for e in entries if e["kind"] == "figure"][:6],
            "review_status": {
                "completed": package["completed_reviews"],
                "pending": package["pending_reviews"],
                "doubts": [],
            },
            "next_week": [objective, objective, {**objective, "action": "Sesión de revisión"}],
            "critical_highlights": list(package["critical"])[:3],
        }
    else:
        raise AssertionError(title)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
