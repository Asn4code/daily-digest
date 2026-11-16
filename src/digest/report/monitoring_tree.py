"""Monitoring-specific bounded source pieces and reduction, with complete lineage."""

from collections.abc import Callable
from typing import Any

from digest.collectors.base import canonical, content_hash
from digest.report.daily import Generate, pending, references
from digest.report.model import Report
from digest.report.packets import plan as plan_packets

LIMIT = 64000
MAX_DEPTH = 8
Measure = Callable[[str, list[str], set[str], dict[str, Any], list[str], str], int]


def build(
    report: Report,
    generate: Generate,
    measure: Measure,
    item: dict[str, Any],
    inputs: set[str],
    scope: set[str],
    context: dict[str, Any],
    *,
    deadline: float,
    limit: int,
) -> None:
    """Reduce complete evidence units; a missing child never becomes an empty summary."""
    limit = min(LIMIT, limit)
    root = "watch:" + item["id"]
    tree: dict[str, Any] = {
        "version": 1,
        "revision": item["revision"],
        "inputs": sorted(inputs),
        "scope": sorted(scope),
        "nodes": {},
        "root": root,
    }
    report.human_context.setdefault("watch_trees", {})[item["id"]] = tree
    entries = {e.id: e for e in report.evidence}
    result_ids = [r.id for r in report.results if r.project in item["projects"]]
    question = {
        "id": item["id"],
        "revision": item["revision"],
        "title": item["values"]["title"],
        "question": item["values"]["question"],
        "projects": item["projects"],
    }
    source_context = {"watch_question": question, "monitoring_level": "source"}
    leaves = []
    covered: set[str] = set()
    # Existing source pieces already passed their own raw-evidence audit. Reuse
    # them whole, including their controls, rather than calling the model twice.
    for key in sorted(report.sections):
        if not key.startswith("source:") or "check:" + key not in report.sections:
            continue
        reused_ids = {e["id"] for e in report.packages[key]["evidence"]}
        if reused_ids and reused_ids <= inputs and reused_ids - covered:
            tree["nodes"][key] = {"kind": "reused", "inputs": sorted(reused_ids), "parents": []}
            leaves.append(key)
            covered.update(reused_ids)

    def source_size(ids: list[str]) -> int:
        return measure("monitoring_context", ids, scope, source_context, result_ids, "full")

    remaining = inputs - covered
    groups = []
    for result in report.results:
        selected = set(result.evidence) & remaining
        if selected:
            groups.append(selected)
            remaining.difference_update(selected)
    for project in sorted({entries[eid].project for eid in remaining}):
        groups.append({eid for eid in remaining if entries[eid].project == project})
    for group in groups:
        packets = plan_packets(
            [entries[eid] for eid in sorted(group)], size=source_size, limit=limit
        )
        for packet in packets:
            ids = packet.evidence
            key = "watchctx:" + item["id"] + ":source:" + content_hash(canonical(ids))[:16]
            leaves.append(key)
            tree["nodes"][key] = {"kind": "source", "inputs": ids, "parents": []}
            if not packet.fits:
                pending(report, key, "monitoring_coherent_unit_budget", "input")
                continue
            generate(
                "conceptual",
                key,
                ids,
                scope,
                source_context,
                result_ids,
                contract="watchctx",
                prompt_name="monitoring_context",
                char_limit=limit,
                cutoff=deadline,
            )
    tree["leaves"] = leaves
    if not leaves or any(key not in report.sections for key in leaves):
        pending(report, root, "monitoring_source_pending")
        return

    def derived(children: list[str], *, final: bool) -> tuple[list[str], dict[str, Any]]:
        pieces = {key: report.sections[key] for key in children}
        prior_refs = references(context.get("previous")) if final else set()
        ids = references(pieces) | prior_refs
        values = {
            **(context if final else {"watch_question": question}),
            "monitoring_level": "assessment" if final else "reduction",
            "parent_pieces": pieces,
            "derived_monitoring": True,
            "_parents": children,
            "_reference_evidence": sorted(prior_refs),
        }
        if final:
            values["current_evidence_ids"] = sorted(set(context["current_evidence_ids"]) & ids)
        return sorted(ids), values

    def fits(children: list[str], *, final: bool) -> bool:
        ids, values = derived(children, final=final)
        return (
            measure(
                "watchlist" if final else "monitoring_context",
                ids,
                scope,
                values,
                result_ids,
                "references",
            )
            <= limit
        )

    current = leaves
    for depth in range(MAX_DEPTH):
        if fits(current, final=True):
            ids, values = derived(current, final=True)
            tree["nodes"][root] = {
                "kind": "assessment",
                "inputs": sorted(inputs),
                "parents": current,
            }
            generate(
                "conceptual",
                root,
                ids,
                scope,
                values,
                result_ids,
                contract="watch",
                prompt_name="watchlist",
                wire_mode="references",
                char_limit=limit,
                cutoff=deadline,
            )
            return
        batches: list[list[str]] = []
        batch: list[str] = []
        for child in current:
            if batch and not fits([*batch, child], final=False):
                batches.append(batch)
                batch = []
            batch.append(child)
        if batch:
            batches.append(batch)
        reduced = []
        for children in batches:
            ids, values = derived(children, final=False)
            key = (
                "watchctx:"
                + item["id"]
                + ":reduce:"
                + str(depth)
                + ":"
                + content_hash(canonical(children))[:16]
            )
            tree["nodes"][key] = {
                "kind": "reduction",
                "inputs": sorted(
                    {eid for child in children for eid in tree["nodes"][child]["inputs"]}
                ),
                "parents": children,
            }
            reduced.append(key)
            if not fits(children, final=False):
                pending(report, key, "monitoring_parent_budget", "input")
                continue
            generate(
                "conceptual",
                key,
                ids,
                scope,
                values,
                result_ids,
                contract="watchctx",
                prompt_name="monitoring_context",
                wire_mode="references",
                char_limit=limit,
                cutoff=deadline,
            )
        if any(key not in report.sections for key in reduced):
            pending(report, root, "monitoring_reduction_pending")
            return
        if len(reduced) >= len(current) and depth:
            pending(report, root, "monitoring_reduction_no_progress", "input")
            return
        current = reduced
    pending(report, root, "monitoring_depth_budget", "input")


def required(report: Report) -> set[str]:
    return {
        key
        for tree in report.human_context.get("watch_trees", {}).values()
        for key in [tree["root"], *tree["nodes"]]
    }


def verify(report: Report) -> None:
    """Bind every derived piece to its exact parents and the complete input inventory."""
    frozen = {s["id"]: s for s in report.watchlist.get("items", [])}
    registered: set[str] = set()
    for ident, tree in report.human_context.get("watch_trees", {}).items():
        item = frozen.get(ident)
        if (
            item is None
            or item["omitted"]
            or tree.get("version") != 1
            or tree.get("revision") != item["revision"]
            or tree.get("root") != "watch:" + ident
        ):
            raise ValueError("Monitoring tree identity changed")
        inputs = set(tree["inputs"])
        all_ids = {e.id for e in report.evidence if e.project in item["projects"]}
        initial = {
            e.id for e in report.evidence if e.project in item["projects"] and not e.context_only
        }
        historical = set(report.human_context.get("watch_history", {}).get(ident, []))
        if (
            not initial | historical <= inputs <= all_ids
            or len(inputs) != len(tree["inputs"])
            or not set(item["privacy_projects"]) <= set(tree["scope"])
        ):
            raise ValueError("Monitoring tree input inventory changed")
        nodes = tree["nodes"]
        leaves = tree["leaves"]
        if (
            not leaves
            or len(leaves) != len(set(leaves))
            or not set(leaves) <= nodes.keys()
            or {eid for key in leaves for eid in nodes[key]["inputs"]} != inputs
            or len(nodes) > len(inputs) * (MAX_DEPTH + 1) + 1
        ):
            raise ValueError("Monitoring source manifest incomplete")
        colors: dict[str, int] = {}

        def walk(
            key: str,
            nodes: dict[str, Any] = nodes,
            colors: dict[str, int] = colors,
            depth: int = 0,
        ) -> None:
            if depth > MAX_DEPTH + 1:
                raise ValueError("Monitoring dependency depth exceeded")
            if key not in nodes or colors.get(key) == 1:
                raise ValueError("Monitoring dependency cycle or missing node")
            if colors.get(key) == 2:
                return
            colors[key] = 1
            for child in nodes[key]["parents"]:
                walk(child, depth=depth + 1)
            colors[key] = 2

        for key in nodes:
            walk(key)
        question = {
            "id": item["id"],
            "revision": item["revision"],
            "title": item["values"]["title"],
            "question": item["values"]["question"],
            "projects": item["projects"],
        }
        for key, node in nodes.items():
            kind, children = node["kind"], node["parents"]
            node_ids = set(node["inputs"])
            if (
                kind not in {"source", "reused", "reduction", "assessment"}
                or not node_ids <= inputs
                or len(node_ids) != len(node["inputs"])
                or len(children) != len(set(children))
                or ((key in leaves) != (kind in {"source", "reused"}))
                or (kind == "assessment" and key != tree["root"])
                or (
                    kind != "reused"
                    and key != tree["root"]
                    and not key.startswith("watchctx:" + ident + ":")
                )
            ):
                raise ValueError("Invalid monitoring node")
            registered.add(key)
            if children and node_ids != {
                eid for child in children for eid in nodes[child]["inputs"]
            }:
                raise ValueError("Monitoring lineage loses input evidence")
            if key not in report.sections:
                continue  # Pending nodes remain required; drafts may retain valid siblings.
            package = report.packages[key]
            context = package["context"]
            package_ids = {e["id"] for e in package["evidence"]}
            if kind == "reused":
                if (
                    not key.startswith("source:")
                    or children
                    or package_ids != node_ids
                    or not set(package["project_ids"]) <= set(tree["scope"])
                ):
                    raise ValueError("Invalid reused monitoring source")
                continue
            if set(package["project_ids"]) != set(tree["scope"]):
                raise ValueError("Monitoring privacy scope narrowed")
            if kind == "source":
                if (
                    children
                    or package.get("parents")
                    or package_ids != node_ids
                    or context.get("watch_question") != question
                    or context.get("monitoring_level") != "source"
                    or context.get("derived_monitoring")
                ):
                    raise ValueError("Monitoring source modified")
            else:
                if (
                    not children
                    or any(child not in report.sections for child in children)
                    or package.get("parents") != children
                    or context.get("parent_pieces")
                    != {child: report.sections[child] for child in children}
                    or context.get("derived_monitoring") is not True
                    or package.get("wire_mode") != "references"
                ):
                    raise ValueError("Monitoring parent binding changed")
                expected = references(context["parent_pieces"])
                if kind == "assessment":
                    expected.update(references(context.get("previous")))
                elif context.get("watch_question") != question:
                    raise ValueError("Monitoring reduction question changed")
                if package_ids != expected:
                    raise ValueError("Monitoring derived evidence changed")
        if tree["root"] in report.sections:
            reached: set[str] = set()

            def visit(key: str, nodes: dict[str, Any] = nodes, reached: set[str] = reached) -> None:
                if key in reached:
                    return
                reached.add(key)
                for child in nodes[key]["parents"]:
                    visit(child)

            visit(tree["root"])
            if reached != set(nodes) or set(nodes[tree["root"]]["inputs"]) != inputs:
                raise ValueError("Monitoring root does not cover every source")
    if any(key.startswith("watchctx:") and key not in registered for key in report.sections):
        raise ValueError("Unregistered monitoring context")


def quoted_parent(quote: str, evidence: list[str], context: dict[str, Any]) -> bool:
    """A derived audit may quote an exact, cited parent claim, never arbitrary context."""
    if context.get("derived_monitoring") is not True:
        return False

    def find(value: Any) -> bool:
        if isinstance(value, dict):
            if (
                isinstance(value.get("text"), str)
                and quote in value["text"]
                and isinstance(value.get("evidence"), list)
                and set(evidence) & set(value["evidence"])
            ):
                return True
            return any(find(v) for v in value.values())
        return isinstance(value, list) and any(find(v) for v in value)

    return find(context.get("parent_pieces", {}))
