"""Deterministic, bounded SVG geometry for a page of captured project tasks."""

import textwrap
from collections import deque
from typing import Any


def layout(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    if len(tasks) > 60:
        raise ValueError("Graph page exceeds limit")
    by_key = {(t["project_id"], t["id"]): t for t in tasks}
    pending = {
        k: {(k[0], dep) for dep in t["deps"] if (k[0], dep) in by_key} for k, t in by_key.items()
    }
    children: dict[tuple[str, str], list[tuple[str, str]]] = {k: [] for k in by_key}
    for child, parents in pending.items():
        for parent in parents:
            children[parent].append(child)
    degrees = {k: len(v) for k, v in pending.items()}
    ready = deque(sorted(k for k, n in degrees.items() if n == 0))
    depth = dict.fromkeys(by_key, 0)
    visited = set()
    while ready:
        parent = ready.popleft()
        visited.add(parent)
        for child in sorted(children[parent]):
            depth[child] = max(depth[child], depth[parent] + 1)
            degrees[child] -= 1
            if not degrees[child]:
                ready.append(child)
    # Cycles are already rejected by Kanvas at collection. Remain finite if an
    # internally inconsistent historical page ever reaches this renderer.
    for k in by_key.keys() - visited:
        depth[k] = 0
    rows: dict[int, int] = {}
    nodes = []
    positions = {}
    for k in sorted(by_key, key=lambda k: (depth[k], -by_key[k]["suggested"], k)):
        column = depth[k]
        row = rows.get(column, 0)
        rows[column] = row + 1
        x, y = 24 + column * 300, 24 + row * 148
        positions[k] = (x, y)
        title = textwrap.wrap(by_key[k]["title"], width=29)[:2]
        nodes.append({"task": by_key[k], "x": x, "y": y, "title_lines": title})
    edges = []
    outside = 0
    for child, task in by_key.items():
        for dep in task["deps"]:
            parent = (child[0], dep)
            if parent not in positions:
                outside += 1
                continue
            x, y = positions[parent]
            right, bottom = positions[child]
            edges.append(
                f"M {x + 252} {y + 52} C {x + 276} {y + 52}, "
                f"{right - 24} {bottom + 52}, {right} {bottom + 52}"
            )
    return {
        "nodes": nodes,
        "edges": edges,
        "outside": outside,
        "cycle": len(visited) != len(by_key),
        "width": max(640, 300 * (max(depth.values(), default=0) + 1)),
        "height": max(240, max(rows.values(), default=1) * 148 + 24),
    }
