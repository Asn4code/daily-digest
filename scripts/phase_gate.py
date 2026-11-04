#!/usr/bin/env python3
"""Puerta de fase de daily-digest.

Comprueba que una fase está bien construida antes de pasar a la siguiente:

  1. archivos   que deben existir (de esta fase y, por regresión, de las anteriores)
  2. reglas     patrones prohibidos en el código (invariantes de AGENTS.md)
  3. comandos   lint, tipos y comandos propios de la fase
  4. tests      escenarios T01..T30 de docs/TESTING.md: cada ID exigido tiene tests y todos pasan
  5. tablero    todas las tareas del grupo de Kanvas de la fase están en «done» (salvo la propia puerta)
  6. revisión   docs/reviews/phase-N.md con veredicto «aprobada» de un revisor distinto del constructor
  7. firma      comprobaciones manuales marcadas y firma de la persona en ese mismo archivo

Uso:
  python scripts/phase_gate.py N                    # puerta completa de la fase N
  python scripts/phase_gate.py N --no-manual        # sin revisión ni firma: resultado PROVISIONAL
  python scripts/phase_gate.py N --host             # incluye comandos marcados host_only (equipo de Rocky)
  python scripts/phase_gate.py N --init-review       # crea docs/reviews/phase-N.md desde la plantilla

Códigos de salida: 0 APROBADA, 1 SUSPENDIDA, 3 PROVISIONAL (todo lo automático pasa; falta revisión o firma).

Solo usa la biblioteca estándar (Python 3.11+). No modifica nada salvo el informe en report_dir
y, con --init-review, la ficha de revisión si no existe.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"
TEXT_SUFFIXES = {
    ".py",
    ".sql",
    ".html",
    ".j2",
    ".jinja",
    ".txt",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".service",
    ".timer",
    ".js",
    ".css",
    ".json",
    ".webmanifest",
    ".cfg",
}
TEST_ID_RE = re.compile(r"(?<![A-Za-z0-9])(T\d{2})(?!\d)")


@dataclass
class Check:
    category: str
    name: str
    status: str
    detail: str = ""


@dataclass
class Gate:
    root: Path
    cfg: dict
    phase: int
    regression: bool
    manual: bool
    host: bool
    checks: list[Check] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers

    def add(self, category: str, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(category, name, status, detail))

    def phases_in_scope(self) -> list[int]:
        defined = sorted(int(k) for k in self.cfg.get("phases", {}))
        if self.phase not in defined:
            sys.exit(f"Fase {self.phase} no definida en gates.toml (definidas: {defined})")
        return [p for p in defined if p <= self.phase] if self.regression else [self.phase]

    def phase_cfg(self, p: int) -> dict:
        return self.cfg["phases"][str(p)]

    # ------------------------------------------------------------------ 1. archivos

    def check_files(self) -> None:
        for p in self.phases_in_scope():
            for rel in self.phase_cfg(p).get("files", []):
                ok = (self.root / rel).exists()
                self.add("archivos", rel, PASS if ok else FAIL, "" if ok else f"falta (fase {p})")

    # ------------------------------------------------------------------ 2. reglas prohibidas

    def iter_files(self, paths: list[str], exclude: list[str]):
        for base in paths:
            target = self.root / base
            if target.is_file():
                candidates = [target]
            elif target.is_dir():
                candidates = [f for f in target.rglob("*") if f.is_file()]
            else:
                continue
            for f in candidates:
                rel = f.relative_to(self.root).as_posix()
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    continue
                if f.suffix in TEXT_SUFFIXES or f.name.endswith(".example.yaml"):
                    yield f, rel

    def check_forbidden(self) -> None:
        rules = self.cfg.get("common", {}).get("forbidden", [])
        for rule in rules:
            regex = re.compile(rule["pattern"])
            allow_marker = f"gate: allow {rule['id']}"
            hits: list[str] = []
            allowed = 0
            for f, rel in self.iter_files(rule.get("paths", []), rule.get("exclude", [])):
                try:
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError as e:
                    hits.append(f"{rel}: no legible ({e})")
                    continue
                for n, line in enumerate(lines, 1):
                    if regex.search(line):
                        if allow_marker in line:
                            allowed += 1
                        else:
                            hits.append(f"{rel}:{n}: {line.strip()[:120]}")
            if hits:
                self.add("reglas", rule["id"], FAIL, f"{rule.get('why', '')}\n" + "\n".join(hits[:20]))
            else:
                note = f"{allowed} excepción(es) marcada(s): el revisor debe justificarlas" if allowed else ""
                self.add("reglas", rule["id"], WARN if allowed else PASS, note)

    # ------------------------------------------------------------------ 3. comandos

    def run_command(self, cmd: dict) -> None:
        name = cmd["name"]
        if cmd.get("host_only") and not self.host:
            self.add("comandos", name, SKIP, "solo en el equipo de Rocky (--host)")
            return
        try:
            proc = subprocess.run(  # gate: allow no-subprocess-outside-proc (script de puerta, fuera de src)
                cmd["run"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=cmd.get("timeout", 900),
            )
        except FileNotFoundError:
            self.add("comandos", name, FAIL, f"no se encuentra el ejecutable: {cmd['run'][0]}")
            return
        except subprocess.TimeoutExpired:
            self.add("comandos", name, FAIL, "tiempo agotado")
            return
        out = proc.stdout + proc.stderr
        if proc.returncode != 0:
            self.add("comandos", name, FAIL, f"código {proc.returncode}\n{out[-1500:]}")
            return
        missing = [s for s in cmd.get("expect_stdout", []) if s not in proc.stdout]
        if missing:
            self.add("comandos", name, FAIL, f"faltan en la salida: {missing}")
        else:
            self.add("comandos", name, PASS)

    def check_commands(self) -> None:
        for cmd in self.cfg.get("common", {}).get("commands", []):
            self.run_command(cmd)
        for cmd in self.phase_cfg(self.phase).get("commands", []):
            self.run_command(cmd)

    # ------------------------------------------------------------------ 4. tests por escenario

    def check_tests(self, report_dir: Path) -> None:
        required: dict[str, int] = {}
        for p in self.phases_in_scope():
            for tid in self.phase_cfg(p).get("tests", []):
                required.setdefault(tid, p)
        if not required:
            self.add("tests", "(ninguno exigido)", PASS)
            return
        junit = report_dir / f"phase-{self.phase}-junit.xml"
        expr = " or ".join(sorted(required))
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
            "-k",
            expr,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,  # gate: allow no-subprocess-outside-proc
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            self.add("tests", "pytest", FAIL, "tiempo agotado")
            return
        if proc.returncode not in (0, 1, 5):
            self.add(
                "tests",
                "pytest",
                FAIL,
                f"pytest terminó con código {proc.returncode}\n{proc.stdout[-1500:]}{proc.stderr[-800:]}",
            )
            return
        results: dict[str, list[tuple[str, str]]] = {tid: [] for tid in required}
        if junit.exists():
            for case in ET.parse(junit).getroot().iter("testcase"):
                name = case.get("name", "")
                outcome = "passed"
                for tag in ("failure", "error", "skipped"):
                    if case.find(tag) is not None:
                        outcome = tag
                for tid in TEST_ID_RE.findall(name):
                    if tid in results:
                        results[tid].append((f"{case.get('classname', '')}::{name}", outcome))
        for tid, cases in sorted(results.items()):
            origin = f"fase {required[tid]}"
            if not cases:
                self.add("tests", tid, FAIL, f"ningún test lleva {tid} en el nombre ({origin})")
                continue
            bad = [f"{n} → {o}" for n, o in cases if o != "passed"]
            if bad:
                self.add("tests", tid, FAIL, f"{origin}\n" + "\n".join(bad))
            else:
                self.add("tests", tid, PASS, f"{len(cases)} test(s), {origin}")

    # ------------------------------------------------------------------ 5. tablero Kanvas

    def check_kanvas(self) -> None:
        board_path = self.root / self.cfg.get("kanvas_board", "kanvas.json")
        group = self.phase_cfg(self.phase).get("kanvas_group")
        if not group:
            self.add("tablero", "grupo", SKIP, "la fase no declara kanvas_group")
            return
        if not board_path.exists():
            self.add(
                "tablero", board_path.name, WARN, "no hay tablero; no se comprueba el estado de las tareas"
            )
            return
        board = json.loads(board_path.read_text(encoding="utf-8"))
        gate_prefix = self.cfg.get("gate_task_prefix", "Puerta de fase")
        tasks = [t for t in board.get("tasks", []) if str(t.get("id", "")).startswith(f"{group}-")]
        if not tasks:
            self.add("tablero", group, FAIL, f"no hay tareas {group}-* en el tablero")
            return
        pending = [
            f"{t['id']} ({t.get('state')}) {t.get('title', '')}"
            for t in tasks
            if not str(t.get("title", "")).startswith(gate_prefix) and t.get("state") != "done"
        ]
        if pending:
            self.add("tablero", group, FAIL, "tareas sin terminar:\n" + "\n".join(pending))
        else:
            self.add("tablero", group, PASS, f"{len(tasks)} tareas del grupo")

    # ------------------------------------------------------------------ 6 y 7. revisión y firma

    def review_path(self) -> Path:
        return self.root / self.cfg.get("reviews_dir", "docs/reviews") / f"phase-{self.phase}.md"

    def check_review(self) -> None:
        path = self.review_path()
        if not self.manual:
            self.add("revisión", path.name, SKIP, "--no-manual")
            self.add("firma", "comprobaciones manuales", SKIP, "--no-manual")
            return
        if not path.exists():
            self.add("revisión", path.name, FAIL, "no existe; créala con --init-review")
            self.add("firma", "comprobaciones manuales", FAIL, "sin ficha de revisión")
            return
        text = path.read_text(encoding="utf-8")
        meta = parse_front_matter(text)
        builder, reviewer = meta.get("builder", "").strip(), meta.get("reviewer", "").strip()
        verdict = meta.get("verdict", "").strip().lower()
        problems = []
        if not reviewer:
            problems.append("falta reviewer")
        if not builder:
            problems.append("falta builder")
        if builder and reviewer and builder.lower() == reviewer.lower():
            problems.append("el revisor debe ser distinto del constructor")
        if verdict != "aprobada":
            problems.append(f"veredicto «{verdict or 'vacío'}» (se exige «aprobada»)")
        if re.search(r"^\s*-\s*\[\s\]\s*\*\*bloqueante\*\*", text, re.M | re.I):
            problems.append("hay hallazgos bloqueantes sin resolver")
        self.add("revisión", path.name, FAIL if problems else PASS, "; ".join(problems))

        unchecked = []
        for item in self.phase_cfg(self.phase).get("manual", []):
            pattern = re.compile(r"^\s*-\s*\[[xX]\]\s*" + re.escape(item), re.M)
            if not pattern.search(text):
                unchecked.append(item)
        signed = re.search(r"^\s*-\s*\[[xX]\]\s*Apruebo la fase", text, re.M)
        detail = []
        if unchecked:
            detail.append("sin marcar:\n" + "\n".join(f"  - {u}" for u in unchecked))
        if not signed:
            detail.append("falta «- [x] Apruebo la fase»")
        self.add("firma", "comprobaciones manuales", FAIL if detail else PASS, "\n".join(detail))

    # ------------------------------------------------------------------ resultado

    def verdict(self) -> str:
        statuses = {c.status for c in self.checks}
        if FAIL in statuses:
            return "SUSPENDIDA"
        if any(c.status == SKIP and c.category in ("revisión", "firma") for c in self.checks):
            return "PROVISIONAL"
        return "APROBADA"

    def report_markdown(self) -> str:
        name = self.phase_cfg(self.phase).get("name", "")
        lines = [
            f"# Puerta de fase {self.phase}: {name}",
            "",
            f"Resultado: **{self.verdict()}** · {dt.datetime.now().astimezone().isoformat(timespec='seconds')}"
            f" · regresión {'sí' if self.regression else 'no'} · host {'sí' if self.host else 'no'}",
            "",
            "| Categoría | Comprobación | Estado |",
            "| --- | --- | --- |",
        ]
        for c in self.checks:
            lines.append(f"| {c.category} | {c.name} | {c.status} |")
        details = [c for c in self.checks if c.detail and c.status != PASS]
        if details:
            lines += ["", "## Detalles", ""]
            for c in details:
                lines += [f"### {c.category} · {c.name} · {c.status}", "", "```text", c.detail, "```", ""]
        return "\n".join(lines) + "\n"


def parse_front_matter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.split("#", 1)[0].strip()
    return out


def init_review(gate: Gate) -> None:
    path = gate.review_path()
    if path.exists():
        print(f"Ya existe {path.relative_to(gate.root)}; no se modifica.")
        return
    pc = gate.phase_cfg(gate.phase)
    manual = "\n".join(f"- [ ] {m}" for m in pc.get("manual", [])) or "- (ninguna)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
phase: {gate.phase}
builder:            # agente o persona que construyó la fase (p. ej. claude-code)
reviewer:           # agente distinto que revisa (p. ej. codex) o sesión nueva sin contexto
verdict: pendiente  # pendiente | cambios | aprobada
date:
---

# Revisión de la fase {gate.phase}: {pc.get("name", "")}

Protocolo en docs/VALIDATION.md. El revisor rellena «Hallazgos» y «Veredicto»; la persona rellena «Firma».

## Informe automático

Adjunta o enlaza `build/gates/phase-{gate.phase}.md`
(resultado de `python scripts/phase_gate.py {gate.phase} --no-manual`).

## Hallazgos

Una línea por hallazgo. Los bloqueantes impiden aprobar hasta que se marquen como resueltos.

- [ ] **bloqueante** …
- [ ] **importante** …
- [ ] **menor** …

## Excepciones «gate: allow» revisadas

- …

## Veredicto del revisor

…

## Firma de la persona

Comprobaciones que solo puedes hacer tú:

{manual}

- [ ] Apruebo la fase
""",
        encoding="utf-8",
    )
    print(f"Creada {path.relative_to(gate.root)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", type=int)
    ap.add_argument("--config", default="docs/gates.toml")
    ap.add_argument("--root", default=".")
    ap.add_argument("--no-regression", action="store_true", help="solo archivos y tests de esta fase")
    ap.add_argument("--no-manual", action="store_true", help="omite revisión y firma (resultado provisional)")
    ap.add_argument("--host", action="store_true", help="incluye comandos host_only")
    ap.add_argument(
        "--only",
        nargs="+",
        choices=["archivos", "reglas", "comandos", "tests", "tablero", "revisión"],
        help="ejecuta solo estas categorías",
    )
    ap.add_argument("--init-review", action="store_true", help="crea la ficha de revisión y termina")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    cfg = tomllib.loads((root / args.config).read_text(encoding="utf-8"))
    gate = Gate(root, cfg, args.phase, not args.no_regression, not args.no_manual, args.host)
    gate.phases_in_scope()  # valida que la fase existe

    if args.init_review:
        init_review(gate)
        return 0

    report_dir = root / cfg.get("report_dir", "build/gates")
    report_dir.mkdir(parents=True, exist_ok=True)
    steps = {
        "archivos": gate.check_files,
        "reglas": gate.check_forbidden,
        "comandos": gate.check_commands,
        "tests": lambda: gate.check_tests(report_dir),
        "tablero": gate.check_kanvas,
        "revisión": gate.check_review,
    }
    for key, fn in steps.items():
        if args.only and key not in args.only:
            continue
        fn()

    report = gate.report_markdown()
    out = report_dir / f"phase-{args.phase}.md"
    out.write_text(report, encoding="utf-8")

    width = max((len(c.name) for c in gate.checks), default=10)
    for c in gate.checks:
        print(f"{c.status:5} {c.category:9} {c.name:<{width}}")
    v = gate.verdict()
    partial = f" — PARCIAL, solo: {', '.join(args.only)}" if args.only else ""
    print(f"\nPuerta de fase {args.phase}: {v}{partial}  (informe: {out.relative_to(root)})")
    if args.only and v == "APROBADA":
        return 3  # una ejecución parcial nunca aprueba la fase
    return {"APROBADA": 0, "SUSPENDIDA": 1, "PROVISIONAL": 3}[v]


if __name__ == "__main__":
    sys.exit(main())
